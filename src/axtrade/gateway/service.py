"""Gateway service orchestrator."""

import asyncio
import signal
import time
from typing import Optional

from ..common import Config, LoopSupervisor, RedisPublisher, SymbolConfig, get_logger, load_config
from .alpaca import AlpacaAdapter
from .base import DataAdapter
from .control import GatewayControlSubscriber
from .ibkr import IBKRAdapter
from .mock import MockAdapter
from .yahoo import YahooAdapter

logger = get_logger(__name__)

# Consecutive tick-publish failures before the error is re-raised to the
# stream supervisor for backoff + alerting.
PUBLISH_FAILURE_ESCALATION_THRESHOLD = 10


class GatewayService:
    """Main gateway service that orchestrates data flow.

    Connects to a data adapter (mock or IBKR), streams ticks,
    publishes them to Redis, and prints to console.
    """

    def __init__(self, config: Config, adapter: Optional[DataAdapter] = None):
        """Initialize gateway service.

        Args:
            config: Application configuration
            adapter: Optional pre-built data adapter (bypasses config-based creation)
        """
        self.config = config
        self._injected_adapter = adapter
        self._adapter: Optional[DataAdapter] = None
        self._publisher: Optional[RedisPublisher] = None
        self._running = False
        self._last_prices: dict[str, float] = {}
        self._stream_supervisor: Optional[LoopSupervisor] = None
        self._control_subscriber: Optional[GatewayControlSubscriber] = None
        self._control_task: Optional[asyncio.Task] = None
        self._publish_failures = 0
        self._last_tick_monotonic: Optional[float] = None
        self._tick_stale_flagged = False
        self._watchdog_task: Optional[asyncio.Task] = None

    def _create_adapter(self) -> DataAdapter:
        """Create the appropriate data adapter based on config.

        If an adapter was injected via the constructor, returns that instead.

        Returns:
            DataAdapter instance
        """
        if self._injected_adapter is not None:
            return self._injected_adapter

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
            logger.critical("redis_connection_failed_at_startup", error=str(e))
            raise

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

        # Start control subscriber for dynamic symbol management
        self._control_subscriber = GatewayControlSubscriber(
            self.config.redis, self.config.gateway
        )
        await self._control_subscriber.connect()
        self._control_task = asyncio.create_task(self._control_loop())
        logger.info("Gateway control subscriber started")

        self._running = True
        self._last_tick_monotonic = time.monotonic()
        if self.config.gateway.tick_staleness_seconds > 0:
            self._watchdog_task = asyncio.create_task(self._staleness_watchdog())
        await self._stream_loop()

    async def stop(self) -> None:
        """Stop the gateway service."""
        logger.info("stopping_gateway")
        self._running = False

        if self._stream_supervisor:
            self._stream_supervisor.stop()

        if self._control_task:
            self._control_task.cancel()
            try:
                await self._control_task
            except asyncio.CancelledError:
                pass

        if self._watchdog_task:
            self._watchdog_task.cancel()
            try:
                await self._watchdog_task
            except asyncio.CancelledError:
                pass

        if self._control_subscriber:
            await self._control_subscriber.disconnect()

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

    async def _control_loop(self) -> None:
        """Listen for gateway control commands and apply them."""
        if not self._control_subscriber or not self._adapter:
            return

        while self._running:
            try:
                async for command in self._control_subscriber.subscribe():
                    if not self._running:
                        break
                    await self._handle_control_command(command)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Gateway control loop error", error=str(e))
                await asyncio.sleep(1.0)

    async def _handle_control_command(self, command) -> None:
        """Handle a gateway control command."""
        if not self._adapter:
            return

        if command.action == "add_symbols":
            configs = [
                SymbolConfig(
                    symbol=s["symbol"],
                    base_price=s.get("base_price", 100.0),
                )
                for s in command.symbols
            ]
            await self._adapter.add_symbols(configs)
            logger.info(
                "Added symbols via control",
                symbols=[s.symbol for s in configs],
            )
        elif command.action == "remove_symbols":
            names = [s["symbol"] for s in command.symbols]
            await self._adapter.remove_symbols(names)
            logger.info("Removed symbols via control", symbols=names)
        else:
            logger.warning("Unknown gateway control action", action=command.action)

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
                    self._last_tick_monotonic = time.monotonic()

                    self._print_tick(tick, change)

                    if self._publisher:
                        try:
                            await self._publisher.publish_tick(tick)
                        except Exception as e:
                            self._publish_failures += 1
                            logger.error(
                                "redis_publish_failed",
                                error=str(e),
                                consecutive_failures=self._publish_failures,
                            )
                            if self._publish_failures >= PUBLISH_FAILURE_ESCALATION_THRESHOLD:
                                self._publish_failures = 0
                                raise
                        else:
                            self._publish_failures = 0
                            # Reset errors on successful iteration
                            self._stream_supervisor.reset_errors()

            except asyncio.CancelledError:
                break
            except Exception as e:
                if not await self._stream_supervisor.handle_error(e):
                    break

    async def _staleness_watchdog(self) -> None:
        """Warn when no ticks have arrived for tick_staleness_seconds.

        Covers all adapters (not just Alpaca's explicit death detection) -
        a source can go quiet without raising anything, e.g. a polling
        adapter that stops updating or a websocket that stalls without
        closing. Quiet markets/overnight make staleness normal, so this
        only warns (once per stale episode) rather than escalating.
        """
        threshold = self.config.gateway.tick_staleness_seconds
        interval = max(0.05, min(30.0, threshold / 4))
        while self._running:
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                return
            if not self._running or self._last_tick_monotonic is None:
                continue
            elapsed = time.monotonic() - self._last_tick_monotonic
            if elapsed > threshold and not self._tick_stale_flagged:
                self._tick_stale_flagged = True
                logger.warning(
                    "tick_stream_stale",
                    seconds_since_last_tick=round(elapsed, 1),
                    threshold=threshold,
                    adapter=self.config.gateway.adapter,
                )
            elif elapsed <= threshold and self._tick_stale_flagged:
                self._tick_stale_flagged = False
                logger.info("tick_stream_resumed")

    def _print_tick(self, tick, change: float) -> None:
        """Log tick data.

        Args:
            tick: Tick data
            change: Price change from last tick
        """
        logger.debug(
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
        stop_task = asyncio.create_task(stop_event.wait())
        done, _ = await asyncio.wait(
            {task, stop_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if task in done:
            stop_task.cancel()
            try:
                await stop_task
            except asyncio.CancelledError:
                pass
            await service.stop()
            task.result()  # propagate a startup/stream crash to the caller
        else:
            await service.stop()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    await run_with_stop()
