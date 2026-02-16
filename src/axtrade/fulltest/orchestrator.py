"""Main orchestrator for full system backtest."""

import asyncio
import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from axtrade.common import (
    Config,
    DatabasePool,
    StrategyInstanceConfig,
    SymbolConfig,
    get_logger,
    load_config,
)
from axtrade.aggregator.service import AggregatorService
from axtrade.discovery.service import DiscoveryService
from axtrade.gateway.service import GatewayService
from axtrade.strategies import STRATEGY_TYPES
from axtrade.strategies.runner import StrategyRunner

from .data import download_historical_alpaca
from .discovery import BacktestDiscoveryRunner
from .isolation import BacktestInfrastructure
from .replay_adapter import ReplayAdapter
from .report import ReportGenerator, format_json_report, format_text_report
from .types import FullBacktestConfig, FullBacktestResult
from .universe import SP500SymbolProvider

logger = get_logger("fulltest.orchestrator")


class FullBacktestOrchestrator:
    """Coordinates a full system backtest.

    Runs all services in-process within a single asyncio event loop,
    using real Redis Streams and TimescaleDB for data flow with
    isolated databases to avoid polluting production.
    """

    def __init__(
        self,
        bt_config: FullBacktestConfig,
        base_config: Optional[Config] = None,
    ):
        self._bt_config = bt_config
        self._base_config = base_config or load_config()

    async def run(self) -> FullBacktestResult:
        """Execute the full backtest.

        Returns:
            FullBacktestResult with all metrics
        """
        start_time = datetime.now(timezone.utc)
        logger.info(
            "Starting full system backtest",
            start=str(self._bt_config.start),
            end=str(self._bt_config.end),
            symbols=len(self._bt_config.symbols),
        )

        # Step 1: Ensure historical data exists (unless skip_download)
        if not self._bt_config.skip_download:
            await self._ensure_data()
        else:
            logger.info("Skipping data download (using existing data)")

        # Step 2: Set up isolated infrastructure
        config = self._build_isolated_config()
        infra = BacktestInfrastructure(
            db_config=self._base_config.database,
            redis_config=config.redis,
            backtest_db_name=self._bt_config.backtest_db_name,
        )
        await infra.setup()

        try:
            # Step 3: Create and run services
            result = await self._run_services(config)
        finally:
            # Step 4: Clean up Redis (DB kept)
            await infra.teardown()

        # Step 5: Generate report
        report_gen = ReportGenerator(
            db_config=self._base_config.database,
            backtest_db_name=self._bt_config.backtest_db_name,
        )
        result = await report_gen.generate(self._bt_config, result)

        result.start_time = start_time
        result.end_time = datetime.now(timezone.utc)

        # Print report
        if self._bt_config.report_format == "json":
            report_text = format_json_report(result)
        else:
            report_text = format_text_report(result)

        print(report_text)

        # Save report to file
        output_dir = Path(self._bt_config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = start_time.astimezone().strftime("%Y%m%d_%H%M%S")
        report_ext = "json" if self._bt_config.report_format == "json" else "txt"
        report_path = output_dir / f"fulltest_{timestamp}.{report_ext}"
        report_path.write_text(report_text)
        logger.info("Report saved", path=str(report_path))

        # Always save JSON sidecar for programmatic comparison
        if self._bt_config.report_format != "json":
            json_report = format_json_report(result)
            json_path = output_dir / f"fulltest_{timestamp}.json"
            json_path.write_text(json_report)
            logger.info("JSON sidecar saved", path=str(json_path))

        return result

    async def _ensure_data(self) -> None:
        """Download any missing historical data."""
        logger.info("Checking historical data...")
        await download_historical_alpaca(
            symbols=self._bt_config.symbols,
            start=self._bt_config.start,
            end=self._bt_config.end,
            interval=self._bt_config.interval,
            data_dir=self._bt_config.data_dir,
        )

    def _build_isolated_config(self) -> Config:
        """Build a config with isolated Redis/DB settings."""
        config = copy.deepcopy(self._base_config)

        # Redis isolation
        config.redis.db = self._bt_config.redis_db
        config.redis.stream_prefix = f"{self._bt_config.stream_prefix}:ticks"

        # Database isolation
        config.database.database = self._bt_config.backtest_db_name

        # Aggregator streams
        config.aggregator.source_stream = f"{self._bt_config.stream_prefix}:ticks:us"
        config.aggregator.consumer_group = f"{self._bt_config.consumer_group_prefix}aggregator"
        config.aggregator.bar_stream_prefix = f"{self._bt_config.stream_prefix}:bars"

        # Strategy streams
        config.strategies.bar_stream = f"{self._bt_config.stream_prefix}:bars:1m:us"
        config.strategies.consumer_group = f"{self._bt_config.consumer_group_prefix}strategies"
        config.strategies.control_channel = f"bt:axtrade:strategy:control"

        # Enable all strategies
        config.strategies.enabled = []
        for stype, sclass in STRATEGY_TYPES.items():
            config.strategies.enabled.append(
                StrategyInstanceConfig(
                    type=stype,
                    id=f"{stype}-bt",
                    enabled=True,
                )
            )

        # Force paper mode
        config.oms.paper_mode = True

        # Set gateway symbols from backtest config
        config.gateway.symbols = [
            SymbolConfig(symbol=s, base_price=100.0)
            for s in self._bt_config.symbols
        ]

        return config

    async def _run_services(self, config: Config) -> FullBacktestResult:
        """Create and run all services, wait for completion."""
        result = FullBacktestResult(
            config=self._bt_config,
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc),
        )

        # Create replay adapter
        replay = ReplayAdapter(
            data_dir=self._bt_config.data_dir,
            ticks_per_bar=self._bt_config.ticks_per_bar,
            start_date=self._bt_config.start,
            end_date=self._bt_config.end,
        )

        # Create services with isolated config
        gateway = GatewayService(config, adapter=replay)
        strategy_runner = StrategyRunner(config)

        # Set up discovery if enabled
        discovery_runner: Optional[BacktestDiscoveryRunner] = None
        if self._bt_config.discovery_enabled:
            db_pool = DatabasePool(config.database)
            await db_pool.connect()

            discovery_service = DiscoveryService(db_pool=db_pool)
            await discovery_service.connect()

            symbol_provider = SP500SymbolProvider()
            discovery_runner = BacktestDiscoveryRunner(
                config=config,
                discovery_service=discovery_service,
                symbol_provider=symbol_provider,
                scan_interval_bars=self._bt_config.discovery_scan_interval_bars,
            )

        # Create aggregator with discovery callback wired in
        aggregator = AggregatorService(
            config,
            on_bar_callback=discovery_runner.on_bar if discovery_runner else None,
        )

        # Run gateway, aggregator, and strategy runner concurrently
        gateway_task = asyncio.create_task(gateway.start())
        aggregator_task = asyncio.create_task(aggregator.start())
        strategy_task = asyncio.create_task(strategy_runner.start())

        logger.info("All services started, waiting for replay completion...")

        # Wait for replay to finish
        await replay.completion_event.wait()
        logger.info("Replay complete, draining pipeline...")

        # Give aggregator time to process remaining ticks
        await asyncio.sleep(2)
        await aggregator.stop()
        logger.info("Aggregator stopped")

        # Give strategy runner time to process remaining bars
        await asyncio.sleep(2)
        await strategy_runner.stop()
        logger.info("Strategy runner stopped")

        # Stop gateway
        await gateway.stop()
        logger.info("Gateway stopped")

        # Cancel any remaining tasks
        for task in [gateway_task, aggregator_task, strategy_task]:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Clean up discovery
        if discovery_runner and self._bt_config.discovery_enabled:
            result.discovery.total_scans = discovery_runner.scan_count
            result.discovery.symbols_discovered = discovery_runner.total_matches
            await db_pool.disconnect()

        # Populate basic stats
        result.total_bars_processed = replay.total_bars
        result.total_ticks_generated = replay.total_ticks

        return result
