"""Aggregator service orchestrator."""

import asyncio
import signal
import uuid

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
            on_bar_callback: Optional async callback invoked after each bar completes
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
        )

        self._running = False
        self._consumer_name = f"aggregator-{uuid.uuid4().hex[:8]}"
        self._consume_supervisor: LoopSupervisor | None = None

        # Write buffer for batched DB inserts
        self._bar_buffer: list[tuple] = []
        self._bar_buffer_size = 100

        # Redis publish buffer for batched bar publishing
        self._publish_buffer: list[tuple] = []

        # Periodic flush task
        self._flush_task: asyncio.Task | None = None
        self._db_flush_interval = 5.0  # seconds
        self._publish_flush_interval = 0.05  # 50ms

        # Track symbols that have been warmed up for indicators
        self._warmed_symbols: set[str] = set()

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
        self._flush_task = asyncio.create_task(self._periodic_flush_loop())
        await self._consume_loop()

    async def _warmup_indicators(self) -> None:
        """Initialize indicator buffers from historical data."""
        if not self._bar_repo:
            return

        # Get symbols from gateway config
        symbols = [s.symbol for s in self.config.gateway.symbols]
        await self._warmup_symbols(symbols)

    async def _warmup_symbols(self, symbols: list[str]) -> None:
        """Warm up indicator buffers for given symbols from DB.

        Args:
            symbols: List of symbols to warm up
        """
        if not self._bar_repo:
            return

        warmup_count = max(
            self.config.indicators.sma_period,
            self.config.indicators.rsi_period + 1,
        ) + 5

        sem = asyncio.Semaphore(10)

        async def warmup_one(symbol: str, interval: str) -> tuple[str, str, list[float]]:
            async with sem:
                closes = await self._bar_repo.get_recent_closes(
                    symbol, interval, warmup_count
                )
                return symbol, interval, closes or []

        tasks = [
            warmup_one(symbol, interval)
            for symbol in symbols
            for interval in self.config.aggregator.intervals
        ]
        results = await asyncio.gather(*tasks)

        for symbol, interval, closes in results:
            if closes:
                self._indicator_engine.initialize_buffer(symbol, interval, closes)
                self.logger.debug(
                    "Warmed up %s %s buffer with %d prices",
                    symbol,
                    interval,
                    len(closes),
                )

        for symbol in symbols:
            self._warmed_symbols.add(symbol)

    async def stop(self) -> None:
        """Stop the aggregator service."""
        self.logger.info("Stopping aggregator service...")
        self._running = False

        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None

        if self._consume_supervisor:
            self._consume_supervisor.stop()

        # Flush remaining bars
        completed = self._engine.flush()
        for bar, interval in completed:
            await self._process_completed_bar(bar, interval)

        # Flush any remaining buffered bars to Redis and DB
        await self._flush_publish_buffer()
        await self._flush_bar_buffer()

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

    async def _flush_publish_buffer(self) -> None:
        """Flush buffered bars to Redis via batch publish."""
        if not self._publish_buffer:
            return

        try:
            await self._publisher.publish_bar_batch(self._publish_buffer)
        except Exception as e:
            self.logger.error("redis_bar_publish_failed", error=str(e))

        self._publish_buffer.clear()

    async def _periodic_flush_loop(self) -> None:
        """Periodically flush publish and DB buffers.

        Publish buffer is flushed every 50ms to naturally batch bars that
        complete at the same boundary. DB bar buffer gets a safety flush
        every 5s to avoid data loss on crash.
        """
        db_elapsed = 0.0
        interval = self._publish_flush_interval
        while self._running:
            await asyncio.sleep(interval)
            if self._publish_buffer:
                await self._flush_publish_buffer()
            db_elapsed += interval
            if db_elapsed >= self._db_flush_interval:
                db_elapsed = 0.0
                if self._bar_buffer:
                    await self._flush_bar_buffer()

    async def _consume_loop(self) -> None:
        """Main consumption loop."""
        if not self._consume_supervisor:
            return

        while self._running:
            try:
                async for tick in self._consumer.consume(self._consumer_name):
                    if not self._running:
                        break

                    # Dynamic indicator warmup for newly discovered symbols
                    if tick.symbol not in self._warmed_symbols:
                        await self._warmup_symbols([tick.symbol])

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

    async def _flush_bar_buffer(self) -> None:
        """Flush buffered bars to database via bulk insert."""
        if not self._bar_buffer or not self._bar_repo:
            return

        # Group by interval for bulk_insert_bars
        by_interval: dict[str, list[tuple]] = {}
        for row in self._bar_buffer:
            interval = row[0]
            # row format: (interval, timestamp, symbol, open, high, low, close, volume, sma_20, rsi_14)
            record = (row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9])
            by_interval.setdefault(interval, []).append(record)

        for interval, rows in by_interval.items():
            await self._bar_repo.bulk_insert_bars(rows, interval)

        self._bar_buffer.clear()

    async def _process_completed_bar(self, bar: Bar, interval: str) -> None:
        """Process a completed bar: calculate indicators, persist, publish."""
        # Calculate indicators (including regime)
        result = self._indicator_engine.process_bar(
            bar.symbol, interval, bar.close, high=bar.high, low=bar.low
        )

        # Buffer bar for batched DB insert
        if self._bar_repo:
            from decimal import Decimal

            self._bar_buffer.append((
                interval,
                bar.timestamp,
                bar.symbol,
                Decimal(str(bar.open)),
                Decimal(str(bar.high)),
                Decimal(str(bar.low)),
                Decimal(str(bar.close)),
                bar.volume,
                Decimal(str(result.sma_20)) if result.sma_20 is not None else None,
                Decimal(str(result.rsi_14)) if result.rsi_14 is not None else None,
            ))
            if len(self._bar_buffer) >= self._bar_buffer_size:
                await self._flush_bar_buffer()

        # Buffer bar for batched Redis publish
        market = getattr(self.config.aggregator, "market", "us")
        indicators = {
            "sma_20": result.sma_20,
            "rsi_14": result.rsi_14,
            "regime": result.regime.value if result.regime else None,
            "trend": result.trend.value if result.trend else None,
            "volatility": result.volatility.value if result.volatility else None,
            "trend_strength": result.trend_strength,
            "volatility_percentile": result.volatility_percentile,
        }
        self._publish_buffer.append((bar, interval, market, indicators))

        # Print to console
        self._print_bar(bar, interval, result.sma_20, result.rsi_14, result.regime)

        if self._on_bar_callback:
            await self._on_bar_callback()

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
