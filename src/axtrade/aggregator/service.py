"""Aggregator service orchestrator."""

import asyncio
import signal
import socket
from datetime import datetime, timezone

from axtrade.common import (
    Bar,
    BarPublisher,
    BarRepository,
    Config,
    DatabasePool,
    LoopSupervisor,
    RedisConsumer,
    get_logger,
    load_config,
    setup_logging,
)
from axtrade.indicators import IndicatorEngine

from .engine import BarEngine


class AggregatorService:
    """Consumes ticks and produces aggregated bars."""

    def __init__(self, config: Config, on_bar_callback=None):
        """Initialize aggregator service.

        Args:
            config: Application configuration
            on_bar_callback: Optional async callback invoked after each bar
                completes, receiving the bar's timestamp (the sim clock in
                a backtest)
        """
        self.config = config
        self.logger = get_logger("aggregator")
        self._on_bar_callback = on_bar_callback

        self._consumer = RedisConsumer(config.redis, config.aggregator)
        self._publisher = BarPublisher(
            config.redis, config.aggregator.bar_stream_prefix
        )
        self._engine = BarEngine(config.aggregator.intervals)

        # Database and indicators
        self._db_pool = DatabasePool(config.database)
        self._bar_repo: BarRepository | None = None
        self._indicator_engine = IndicatorEngine(
            sma_period=config.indicators.sma_period,
            rsi_period=config.indicators.rsi_period,
            bb_period=config.indicators.bb_period,
            bb_std=config.indicators.bb_std,
            atr_period=config.indicators.atr_period,
            regime_sma_short=config.indicators.regime.sma_short_period,
            regime_sma_long=config.indicators.regime.sma_long_period,
            regime_volatility_lookback=config.indicators.regime.volatility_lookback,
        )

        self._running = False
        self._consumer_name = f"aggregator-{socket.gethostname()}"
        self._consume_supervisor: LoopSupervisor | None = None

    async def start(self) -> None:
        """Start the aggregator service."""
        self.logger.info("Starting aggregator service...")

        # Connect to database
        await self._db_pool.connect()
        self._bar_repo = BarRepository(self._db_pool)
        self.logger.info("Connected to TimescaleDB")

        # Warm up indicator buffers from historical data
        await self._warmup_indicators()

        await self._consumer.connect()
        await self._publisher.connect()

        self.logger.info(
            "Connected to Redis, consuming from %s",
            self.config.aggregator.source_stream,
        )
        self.logger.info("Aggregating intervals: %s", self.config.aggregator.intervals)

        # Initialize loop supervisor
        self._consume_supervisor = LoopSupervisor(
            name="aggregator_consume",
            alert_after=3,
            alert_callback=self._on_loop_failure,
        )

        self._running = True
        await self._consume_loop()

    async def _warmup_indicators(self) -> None:
        """Initialize indicator buffers from historical data."""
        if not self._bar_repo:
            return

        # Get symbols from gateway config
        symbols = [s.symbol for s in self.config.gateway.symbols]
        warmup_count = max(
            self.config.indicators.sma_period,
            self.config.indicators.rsi_period + 1,
            self.config.indicators.bb_period,
            self.config.indicators.atr_period + 1,
        ) + 5

        for symbol in symbols:
            for interval in self.config.aggregator.intervals:
                closes = await self._bar_repo.get_recent_closes(
                    symbol, interval, warmup_count
                )
                if closes:
                    self._indicator_engine.initialize_buffer(symbol, interval, closes)
                    self.logger.debug(
                        "Warmed up %s %s buffer with %d prices",
                        symbol,
                        interval,
                        len(closes),
                    )

    async def stop(self) -> None:
        """Stop the aggregator service."""
        self.logger.info("Stopping aggregator service...")
        self._running = False

        if self._consume_supervisor:
            self._consume_supervisor.stop()

        # Flush remaining bars. Only bars whose window has fully elapsed by
        # now are safe to persist/publish; true mid-window partials (audit
        # P2-8) are dropped rather than upserted over the DB row with an
        # incomplete OHLCV.
        completed, partial = self._engine.flush(as_of=datetime.now(timezone.utc))
        for bar, interval in completed:
            await self._process_completed_bar(bar, interval)
        if partial:
            self.logger.warning(
                "partial_bars_dropped_on_shutdown",
                count=len(partial),
                bars=[(b.symbol, interval, b.timestamp.isoformat()) for b, interval in partial],
            )

        await self._consumer.disconnect()
        await self._publisher.disconnect()
        await self._db_pool.disconnect()

        self.logger.info("Aggregator service stopped")

    async def _on_loop_failure(self, loop_name: str, error: Exception) -> None:
        """Alert on repeated loop failures.

        Args:
            loop_name: Name of the failing loop
            error: The exception that caused the failure
        """
        self.logger.critical(
            "Critical loop failure",
            loop=loop_name,
            error=str(error),
            error_type=type(error).__name__,
        )

    async def _consume_loop(self) -> None:
        """Main consumption loop."""
        if not self._consume_supervisor:
            return

        while self._running:
            try:
                async for tick in self._consumer.consume(self._consumer_name):
                    if not self._running:
                        break

                    completed = self._engine.process_tick(tick)
                    for bar, interval in completed:
                        await self._process_completed_bar(bar, interval)

                    # Reset errors on successful iteration
                    self._consume_supervisor.reset_errors()

            except asyncio.CancelledError:
                break
            except Exception as e:
                if not await self._consume_supervisor.handle_error(e):
                    break

    async def _process_completed_bar(self, bar: Bar, interval: str) -> None:
        """Process a completed bar: calculate indicators, persist, publish."""
        # Calculate indicators (including regime)
        result = self._indicator_engine.process_bar(
            bar.symbol, interval, bar.close, high=bar.high, low=bar.low
        )

        # Persist to database
        if self._bar_repo:
            await self._bar_repo.insert_bar(
                bar=bar,
                interval=interval,
                sma_20=result.sma_20,
                rsi_14=result.rsi_14,
            )

        # Publish to Redis (with indicators and regime for strategy consumption)
        await self._publisher.publish_bar(
            bar,
            interval,
            market="us",
            sma_20=result.sma_20,
            rsi_14=result.rsi_14,
            bb_upper=result.bb_upper,
            bb_middle=result.bb_middle,
            bb_lower=result.bb_lower,
            atr=result.atr,
            regime=result.regime.value if result.regime else None,
            trend=result.trend.value if result.trend else None,
            volatility=result.volatility.value if result.volatility else None,
            trend_strength=result.trend_strength,
            volatility_percentile=result.volatility_percentile,
        )

        # Print to console
        self._print_bar(bar, interval, result.sma_20, result.rsi_14, result.regime)

        if self._on_bar_callback:
            await self._on_bar_callback(bar.timestamp)

    def _print_bar(
        self,
        bar: Bar,
        interval: str,
        sma_20: float | None,
        rsi_14: float | None,
        regime: "MarketRegime | None" = None,
    ) -> None:
        """Log a completed bar."""
        from axtrade.indicators import MarketRegime

        self.logger.debug(
            "bar",
            symbol=bar.symbol,
            interval=interval,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            sma_20=round(sma_20, 2) if sma_20 else None,
            rsi_14=round(rsi_14, 1) if rsi_14 else None,
            regime=regime.value if regime else None,
        )


async def main() -> None:
    """Main entry point."""
    setup_logging(log_name="aggregator")
    config = load_config()
    service = AggregatorService(config)

    loop = asyncio.get_running_loop()

    def signal_handler() -> None:
        asyncio.create_task(service.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await service.start()
    except KeyboardInterrupt:
        pass
    finally:
        await service.stop()


def run() -> None:
    """Run the aggregator service."""
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
