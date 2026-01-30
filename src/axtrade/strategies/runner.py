"""Strategy runner service."""

import asyncio
import signal
import uuid
from typing import Optional

from axtrade.common import (
    BarConsumer,
    Config,
    DatabasePool,
    get_logger,
    load_config,
    setup_logging,
)
from axtrade.oms import OrderManager

from . import STRATEGY_TYPES
from .base import BarWithIndicators, BaseStrategy


class StrategyRunner:
    """Runs trading strategies by consuming bars and routing orders."""

    def __init__(self, config: Config):
        self.config = config
        self.logger = get_logger("strategy_runner")

        self._db_pool: Optional[DatabasePool] = None
        self._bar_consumer: Optional[BarConsumer] = None
        self._order_manager: Optional[OrderManager] = None
        self._strategies: dict[str, BaseStrategy] = {}
        self._running = False
        self._consumer_name = f"strategy-runner-{uuid.uuid4().hex[:8]}"

    async def start(self) -> None:
        """Start the strategy runner."""
        self.logger.info("Starting strategy runner...")

        # Connect to database
        self._db_pool = DatabasePool(self.config.database)
        await self._db_pool.connect()
        self.logger.info("Connected to database")

        # Initialize order manager
        self._order_manager = OrderManager(self.config, self._db_pool)
        await self._order_manager.connect()
        self.logger.info("Order manager initialized (paper_mode=%s)", self.config.oms.paper_mode)

        # Load strategies
        self._load_strategies()

        # Load existing positions into strategies
        await self._load_positions()

        # Connect bar consumer
        self._bar_consumer = BarConsumer(self.config.redis, self.config.strategies)
        await self._bar_consumer.connect()
        self.logger.info(
            "Connected to bar stream: %s",
            self.config.strategies.bar_stream,
        )

        self._running = True
        await self._consume_loop()

    def _load_strategies(self) -> None:
        """Load enabled strategies from config."""
        for strat_config in self.config.strategies.enabled:
            if not strat_config.enabled:
                continue

            strategy_class = STRATEGY_TYPES.get(strat_config.type)
            if not strategy_class:
                self.logger.warning(
                    "Unknown strategy type: %s",
                    strat_config.type,
                )
                continue

            strategy = strategy_class(
                strategy_id=strat_config.id,
                config=strat_config.config,
            )
            self._strategies[strategy.strategy_id] = strategy

            self.logger.info(
                "Loaded strategy: %s (%s)",
                strategy.name,
                strategy.strategy_id,
            )

        if not self._strategies:
            self.logger.warning("No strategies loaded")

    async def _load_positions(self) -> None:
        """Load existing positions into strategies."""
        if not self._order_manager:
            return

        for strategy_id, strategy in self._strategies.items():
            positions = await self._order_manager.get_open_positions(strategy_id)
            for position in positions:
                strategy.update_position(position)
                self.logger.info(
                    "Loaded position: %s %s qty=%s @ %s",
                    strategy_id,
                    position.symbol,
                    position.quantity,
                    position.avg_entry_price,
                )

    async def stop(self) -> None:
        """Stop the strategy runner."""
        self.logger.info("Stopping strategy runner...")
        self._running = False

        if self._bar_consumer:
            await self._bar_consumer.disconnect()

        if self._order_manager:
            await self._order_manager.disconnect()

        if self._db_pool:
            await self._db_pool.disconnect()

        self.logger.info("Strategy runner stopped")

    async def _consume_loop(self) -> None:
        """Main loop consuming bars and feeding strategies."""
        if not self._bar_consumer or not self._order_manager:
            return

        try:
            async for bar_data in self._bar_consumer.consume(self._consumer_name):
                if not self._running:
                    break

                # Convert to BarWithIndicators
                data = BarWithIndicators(
                    bar=bar_data["bar"],
                    sma_20=bar_data.get("sma_20"),
                    rsi_14=bar_data.get("rsi_14"),
                )

                # Update price cache in order manager
                self._order_manager.update_price(data.symbol, data.close)

                # Run each strategy
                for strategy in self._strategies.values():
                    if not strategy.enabled:
                        continue

                    try:
                        order = strategy.on_bar(data)
                        if order:
                            self._log_signal(strategy, data, order)
                            await self._order_manager.submit_order(order)

                            # Update local position after fill (in paper mode, immediate)
                            position = await self._order_manager.get_position(
                                strategy.strategy_id, order.symbol
                            )
                            if position:
                                strategy.update_position(position)
                            else:
                                strategy.clear_position(order.symbol)

                    except Exception as e:
                        self.logger.error(
                            "Strategy error: %s - %s",
                            strategy.name,
                            str(e),
                        )

        except asyncio.CancelledError:
            pass

    def _log_signal(
        self,
        strategy: BaseStrategy,
        data: BarWithIndicators,
        order,
    ) -> None:
        """Log a trading signal to console."""
        bar = data.bar
        rsi_str = f"RSI={data.rsi_14:.1f}" if data.rsi_14 else "RSI=-"
        sma_str = f"SMA={data.sma_20:.2f}" if data.sma_20 else "SMA=-"

        print(
            f"[{bar.timestamp:%H:%M:%S}] {strategy.name}: "
            f"{order.side.value.upper()} signal {bar.symbol} "
            f"({rsi_str}, {sma_str}, price={bar.close:.2f})"
        )


async def main() -> None:
    """Main entry point."""
    setup_logging()
    config = load_config()
    runner = StrategyRunner(config)

    loop = asyncio.get_running_loop()

    def signal_handler() -> None:
        asyncio.create_task(runner.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        await runner.start()
    except KeyboardInterrupt:
        pass
    finally:
        await runner.stop()


def run() -> None:
    """Run the strategy runner."""
    asyncio.run(main())


if __name__ == "__main__":
    run()
