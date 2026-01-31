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
    RedisConsumer,
    get_logger,
    load_config,
    setup_logging,
)
from axtrade.indicators import IndicatorEngine

from .engine import BarEngine


class AggregatorService:
    """Consumes ticks and produces aggregated bars."""

    def __init__(self, config: Config):
        """Initialize aggregator service.

        Args:
            config: Application configuration
        """
        self.config = config
        self.logger = get_logger("aggregator")

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

        # Flush remaining bars
        completed = self._engine.flush()
        for bar, interval in completed:
            await self._process_completed_bar(bar, interval)

        await self._consumer.disconnect()
        await self._publisher.disconnect()
        await self._db_pool.disconnect()

        self.logger.info("Aggregator service stopped")

    async def _consume_loop(self) -> None:
        """Main consumption loop."""
        try:
            async for tick in self._consumer.consume(self._consumer_name):
                if not self._running:
                    break

                completed = self._engine.process_tick(tick)
                for bar, interval in completed:
                    await self._process_completed_bar(bar, interval)
        except asyncio.CancelledError:
            pass

    async def _process_completed_bar(self, bar: Bar, interval: str) -> None:
        """Process a completed bar: calculate indicators, persist, publish."""
        # Calculate indicators
        result = self._indicator_engine.process_bar(bar.symbol, interval, bar.close)

        # Persist to database
        if self._bar_repo:
            await self._bar_repo.insert_bar(
                bar=bar,
                interval=interval,
                sma_20=result.sma_20,
                rsi_14=result.rsi_14,
            )

        # Publish to Redis (with indicators for strategy consumption)
        await self._publisher.publish_bar(
            bar, interval, market="us", sma_20=result.sma_20, rsi_14=result.rsi_14
        )

        # Print to console
        self._print_bar(bar, interval, result.sma_20, result.rsi_14)

    def _print_bar(
        self,
        bar: Bar,
        interval: str,
        sma_20: float | None,
        rsi_14: float | None,
    ) -> None:
        """Log a completed bar."""
        self.logger.info(
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
