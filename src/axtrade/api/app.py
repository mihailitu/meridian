"""FastAPI application factory."""

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from axtrade.alerts import AlertRepository, AlertService, HealthMonitor, LogChannel
from axtrade.common import Config, DatabasePool, get_logger, load_config, setup_logging
from axtrade.discovery import ConfigSymbolProvider, DiscoveryRunner, DiscoveryService
from axtrade.gateway.control import GatewayControlPublisher
from axtrade.oms.repository import OrderRepository, PositionRepository
from axtrade.strategies.control import StrategyControlPublisher, StrategyStateRepository

from .dependencies import state
from .routes import alerts, analytics, discovery, gateway, health, markets, ml, orders, pnl, positions, regime, strategies, ws

logger = get_logger("api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    config = app.state.config

    # Initialize alert system first (no external dependencies)
    state.alert_repo = AlertRepository(max_alerts=1000)
    state.alert_service = AlertService(default_dedupe_seconds=60)
    state.health_monitor = HealthMonitor(
        alert_service=state.alert_service,
        heartbeat_timeout=30.0,
    )

    # Add log channel to alert service
    log_channel = LogChannel(
        repository=state.alert_repo,
        broadcast_callback=ws.broadcast_alert,
    )
    state.alert_service.add_channel(log_channel)
    logger.info("Alert system initialized")

    # Connect to database
    state.db_pool = DatabasePool(config.database)
    await state.db_pool.connect()
    logger.info("Connected to database")

    # Initialize repositories
    state.order_repo = OrderRepository(state.db_pool)
    state.position_repo = PositionRepository(state.db_pool)
    logger.info("Repositories initialized")

    # Initialize strategy control components
    state.strategies_config = config.strategies
    state.strategy_state_repo = StrategyStateRepository(state.db_pool)
    state.strategy_control = StrategyControlPublisher(config.redis, config.strategies)
    await state.strategy_control.connect()
    logger.info("Strategy control initialized")

    # Initialize discovery service and background scanner
    state.discovery_service = DiscoveryService(db_pool=state.db_pool)
    await state.discovery_service.connect()

    # Set up gateway control publisher if auto_subscribe is enabled
    gateway_control: GatewayControlPublisher | None = None
    if config.discovery.auto_subscribe:
        gateway_control = GatewayControlPublisher(config.redis, config.gateway)
        await gateway_control.connect()
        logger.info("Gateway control publisher initialized for auto-subscribe")

    discovery_runner = DiscoveryRunner(
        config=config,
        discovery_service=state.discovery_service,
        symbol_provider=ConfigSymbolProvider(config),
        alert_service=state.alert_service,
        gateway_control=gateway_control,
    )
    discovery_task = asyncio.create_task(discovery_runner.start())
    logger.info("Discovery scanner initialized")

    yield

    # Cleanup
    discovery_runner_stop = discovery_runner.stop()
    await discovery_runner_stop
    discovery_task.cancel()
    try:
        await discovery_task
    except asyncio.CancelledError:
        pass

    if gateway_control:
        await gateway_control.disconnect()

    if state.strategy_control:
        await state.strategy_control.disconnect()

    if state.db_pool:
        await state.db_pool.disconnect()
        logger.info("Disconnected from database")


def create_app(config: Config) -> FastAPI:
    """Create FastAPI application.

    Args:
        config: Application configuration

    Returns:
        Configured FastAPI app
    """
    app = FastAPI(
        title="axtrade API",
        description="Trading platform monitoring API",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Store config in app state
    app.state.config = config

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.api.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # API routes
    app.include_router(positions.router, prefix="/api", tags=["positions"])
    app.include_router(orders.router, prefix="/api", tags=["orders"])
    app.include_router(pnl.router, prefix="/api", tags=["pnl"])
    app.include_router(alerts.router, prefix="/api", tags=["alerts"])
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(analytics.router, prefix="/api", tags=["analytics"])
    app.include_router(strategies.router, prefix="/api", tags=["strategies"])
    app.include_router(regime.router, prefix="/api", tags=["regime"])
    app.include_router(discovery.router, prefix="/api", tags=["discovery"])
    app.include_router(markets.router, prefix="/api", tags=["markets"])
    app.include_router(ml.router, prefix="/api", tags=["ml"])
    app.include_router(gateway.router, prefix="/api", tags=["gateway"])
    app.include_router(ws.router, tags=["websocket"])

    @app.get("/health")
    async def health_check():
        """Health check endpoint."""
        return {"status": "ok"}

    # Serve frontend static files
    frontend_dist = Path(__file__).parent.parent / "web" / "ui" / "dist"
    if frontend_dist.exists():
        # Mount static assets (js, css, etc.)
        app.mount("/assets", StaticFiles(directory=frontend_dist / "assets"), name="assets")

        @app.get("/")
        async def serve_spa_root():
            """Serve frontend index.html at root."""
            return FileResponse(frontend_dist / "index.html")

        @app.get("/{path:path}")
        async def serve_spa(path: str):
            """Serve frontend for SPA routing."""
            # Check if it's a static file
            file_path = frontend_dist / path
            if file_path.exists() and file_path.is_file():
                return FileResponse(file_path)
            # Otherwise serve index.html for SPA routing
            return FileResponse(frontend_dist / "index.html")
    else:
        @app.get("/")
        async def root():
            """API root endpoint (frontend not built)."""
            return {
                "message": "axtrade API",
                "docs": "/docs",
                "note": "Frontend not built. Run: cd src/axtrade/web/ui && npm run build",
            }

    return app


async def main() -> None:
    """Run the API server."""
    import uvicorn

    setup_logging(log_name="api")
    config = load_config()

    logger.info(
        "Starting API server",
        host=config.api.host,
        port=config.api.port,
    )

    app = create_app(config)

    server_config = uvicorn.Config(
        app,
        host=config.api.host,
        port=config.api.port,
        log_level="info",
    )
    server = uvicorn.Server(server_config)
    await server.serve()


def run() -> None:
    """Run the API server synchronously."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
