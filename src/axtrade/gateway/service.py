"""Gateway service orchestrator."""

import asyncio
import signal
from typing import Optional

from ..common import Config, LoopSupervisor, RedisPublisher, get_logger, load_config
from .alpaca import AlpacaAdapter
from .base import DataAdapter
from .ibkr import IBKRAdapter
from .mock import MockAdapter
from .yahoo import YahooAdapter

logger = get_logger(__name__)


class GatewayService:
    """Main gateway service that orchestrates data flow.

    Connects to a data adapter (mock or IBKR), streams ticks,
    publishes them to Redis, and prints to console.
    """

    def __init__(self, config: Config):
        """Initialize gateway service.

        Args:
            config: Application configuration
        """
        self.config = config
        self._adapter: Optional[DataAdapter] = None
        self._publisher: Optional[RedisPublisher] = None
        self._running = False
        self._last_prices: dict[str, float] = {}
        self._stream_supervisor: Optional[LoopSupervisor] = None

    def _create_adapter(self) -> DataAdapter:
        """Create the appropriate data adapter based on config.

        Returns:
            DataAdapter instance
        """
        adapter_type = self.config.gateway.adapter

        if adapter_type == "mock":
            return MockAdapter(self.config.gateway.mock)
        elif adapter_type == "ibkr":
            return IBKRAdapter(self.config.gateway.ibkr)
        elif adapter_type == "alpaca":
            return AlpacaAdapter(self.config.gateway.alpaca)
        elif adapter_type == "yahoo":
            return YahooAdapter(self.config.gateway.yahoo)
        else:
            raise ValueError(f"Unknown adapter type: {adapter_type}")

    async def start(self) -> None:
        """Start the gateway service."""
        logger.info("starting_gateway", adapter=self.config.gateway.adapter)

        self._adapter = self._create_adapter()
        self._publisher = RedisPublisher(self.config.redis)

        await self._adapter.connect()
        logger.info("adapter_connected", name=self._adapter.name)

        try:
            await self._publisher.connect()
            logger.info("redis_connected")
        except Exception as e:
            logger.warning("redis_connection_failed", error=str(e))
            logger.info("continuing_without_redis")
            self._publisher = None

        await self._adapter.subscribe(self.config.gateway.symbols)
        logger.info(
            "subscribed_to_symbols",
            count=len(self.config.gateway.symbols),
        )

        # Initialize loop supervisor
        self._stream_supervisor = LoopSupervisor(
            name="gateway_stream",
            alert_after=3,
            alert_callback=self._on_loop_failure,
        )

        self._running = True
        await self._stream_loop()

    async def stop(self) -> None:
        """Stop the gateway service."""
        logger.info("stopping_gateway")
        self._running = False

        if self._stream_supervisor:
            self._stream_supervisor.stop()

        if self._adapter:
            await self._adapter.disconnect()

        if self._publisher:
            await self._publisher.disconnect()

    async def _on_loop_failure(self, loop_name: str, error: Exception) -> None:
        """Alert on repeated loop failures.

        Args:
            loop_name: Name of the failing loop
            error: The exception that caused the failure
        """
        logger.critical(
            "Critical loop failure",
            loop=loop_name,
            error=str(error),
            error_type=type(error).__name__,
        )

    async def _stream_loop(self) -> None:
        """Main loop that streams and processes ticks."""
        if not self._adapter or not self._stream_supervisor:
            return

        while self._running:
            try:
                async for tick in self._adapter.stream_ticks():
                    if not self._running:
                        break

                    last_price = self._last_prices.get(tick.symbol)
                    change = tick.price - last_price if last_price else 0.0
                    self._last_prices[tick.symbol] = tick.price

                    self._print_tick(tick, change)

                    if self._publisher:
                        try:
                            await self._publisher.publish_tick(tick)
                        except Exception as e:
                            logger.error("redis_publish_failed", error=str(e))

                    # Reset errors on successful iteration
                    self._stream_supervisor.reset_errors()

            except asyncio.CancelledError:
                break
            except Exception as e:
                if not await self._stream_supervisor.handle_error(e):
                    break

    def _print_tick(self, tick, change: float) -> None:
        """Log tick data.

        Args:
            tick: Tick data
            change: Price change from last tick
        """
        logger.info(
            "tick",
            symbol=tick.symbol,
            price=tick.price,
            change=round(change, 2),
        )


async def run_gateway(config_path: Optional[str] = None, adapter: Optional[str] = None) -> None:
    """Run the gateway service.

    Args:
        config_path: Path to config file
        adapter: Override adapter type (mock/ibkr)
    """
    from pathlib import Path

    config = load_config(Path(config_path) if config_path else None)

    if adapter:
        config.gateway.adapter = adapter

    service = GatewayService(config)

    loop = asyncio.get_event_loop()
    stop_event = asyncio.Event()

    def handle_signal():
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, handle_signal)

    async def run_with_stop():
        task = asyncio.create_task(service.start())
        await stop_event.wait()
        await service.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    await run_with_stop()
