"""Strategy runner service."""

import asyncio
import re
import signal
import uuid
from typing import Optional

from axtrade.common import (
    BarConsumer,
    Config,
    DatabasePool,
    LoopSupervisor,
    get_logger,
    load_config,
    setup_logging,
)
from axtrade.discovery import ConfigSymbolProvider, DiscoveryRunner
from axtrade.discovery.service import DiscoveryService
from axtrade.gateway.control import GatewayControlPublisher
from axtrade.indicators import MarketRegime, MarketTrend, VolatilityState
from axtrade.oms import Fill, Order, OrderManager, OrderSide
from axtrade.oms.repository import PositionRepository

from . import STRATEGY_TYPES
from .base import BarWithIndicators, BaseStrategy
from .control import StrategyControlSubscriber, StrategyStateRepository


class StrategyRunner:
    """Runs trading strategies by consuming bars and routing orders."""

    def __init__(self, config: Config, discovery_service: Optional[DiscoveryService] = None):
        self.config = config
        self.logger = get_logger("strategy_runner")

        self._db_pool: Optional[DatabasePool] = None
        self._bar_consumer: Optional[BarConsumer] = None
        self._order_manager: Optional[OrderManager] = None
        self._strategies: dict[str, BaseStrategy] = {}
        self._running = False
        self._consumer_name = f"strategy-runner-{uuid.uuid4().hex[:8]}"
        self._state_repo: Optional[StrategyStateRepository] = None
        self._control_subscriber: Optional[StrategyControlSubscriber] = None
        self._control_task: Optional[asyncio.Task] = None
        self._control_supervisor: Optional[LoopSupervisor] = None
        self._consume_supervisor: Optional[LoopSupervisor] = None
        self._discovery_service = discovery_service
        self._discovery_runner: Optional[DiscoveryRunner] = None
        self._discovery_task: Optional[asyncio.Task] = None
        self._gateway_control: Optional[GatewayControlPublisher] = None
        self._logged_errors: set[str] = set()
        self._current_trading_date: Optional[str] = None

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
        self._order_manager.on_fill(self._on_order_manager_fill)
        self.logger.info("Order manager initialized (paper_mode=%s)", self.config.oms.paper_mode)

        # Load strategies
        self._load_strategies()

        # Inject discovery service into strategies that support it
        if self._discovery_service:
            for strategy in self._strategies.values():
                if hasattr(strategy, "set_discovery_service"):
                    strategy.set_discovery_service(self._discovery_service)
                    self.logger.info(
                        "Injected discovery service into strategy",
                        strategy_id=strategy.strategy_id,
                    )

        # Start the discovery scanner in-process (audit P1-3): trading must
        # not depend on the API process for discovery_momentum to see fresh
        # scores, so the scanner lives here now, matching fulltest's
        # in-process wiring. Runs regardless of whether a discovery_momentum
        # strategy is loaded, mirroring the API's previous unconditional
        # behavior (other consumers may still want fresh discoveries/gateway
        # auto-subscribe).
        if self.config.discovery.enabled:
            if self._discovery_service is None:
                self._discovery_service = DiscoveryService(db_pool=self._db_pool)
                await self._discovery_service.connect()
                for strategy in self._strategies.values():
                    if hasattr(strategy, "set_discovery_service"):
                        strategy.set_discovery_service(self._discovery_service)
                        self.logger.info(
                            "Injected discovery service into strategy",
                            strategy_id=strategy.strategy_id,
                        )

            if self.config.discovery.auto_subscribe:
                self._gateway_control = GatewayControlPublisher(
                    self.config.redis, self.config.gateway
                )
                await self._gateway_control.connect()
                self.logger.info("Gateway control publisher initialized for auto-subscribe")

            position_repo = PositionRepository(self._db_pool)

            self._discovery_runner = DiscoveryRunner(
                config=self.config,
                discovery_service=self._discovery_service,
                symbol_provider=ConfigSymbolProvider(self.config),
                alert_service=None,
                gateway_control=self._gateway_control,
                position_repo=position_repo,
            )
            self._discovery_task = asyncio.create_task(self._discovery_runner.start())
            self.logger.info("Discovery scanner started")

        # Initialize state repository and apply persisted state
        self._state_repo = StrategyStateRepository(self._db_pool)
        await self._apply_persisted_state()

        # Load existing positions into strategies
        await self._load_positions()

        # Initialize loop supervisors
        self._control_supervisor = LoopSupervisor(
            name="strategy_control",
            alert_after=3,
            alert_callback=self._on_loop_failure,
        )
        self._consume_supervisor = LoopSupervisor(
            name="strategy_consume",
            alert_after=3,
            alert_callback=self._on_loop_failure,
        )

        # Start control subscriber
        self._control_subscriber = StrategyControlSubscriber(
            self.config.redis, self.config.strategies
        )
        await self._control_subscriber.connect()
        self._control_task = asyncio.create_task(self._control_loop())
        self.logger.info("Control subscriber started")

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

    async def _on_order_manager_fill(self, fill: Fill) -> None:
        """Route a fill from OrderManager to the strategy that submitted it.

        Registered as an async fill callback on OrderManager (which awaits
        it inside _on_broker_fill, itself under _fill_lock, so the position
        row this re-reads already reflects the fill). This is what makes
        fill routing correct for async brokers (IBKR): the post-submit poll
        in _consume_loop only catches fills that already landed by the time
        submit_order returns, which is only ever true for PaperBroker.

        Args:
            fill: Fill notification from the broker
        """
        strategy = self._strategies.get(fill.strategy_id)
        if not strategy or not self._order_manager:
            return

        position = await self._order_manager.get_position(fill.strategy_id, fill.symbol)
        if position:
            strategy.update_position(position)
        else:
            strategy.clear_position(fill.symbol)

        try:
            strategy.on_fill(fill)
        except Exception as e:
            self.logger.error(
                "Strategy on_fill error",
                strategy_id=fill.strategy_id,
                symbol=fill.symbol,
                error=str(e),
            )

    async def stop(self) -> None:
        """Stop the strategy runner."""
        self.logger.info("Stopping strategy runner...")
        self._running = False

        if self._control_supervisor:
            self._control_supervisor.stop()

        if self._consume_supervisor:
            self._consume_supervisor.stop()

        if self._control_task:
            self._control_task.cancel()
            try:
                await self._control_task
            except asyncio.CancelledError:
                pass

        if self._control_subscriber:
            await self._control_subscriber.disconnect()

        if self._discovery_runner:
            await self._discovery_runner.stop()

        if self._discovery_task:
            self._discovery_task.cancel()
            try:
                await self._discovery_task
            except asyncio.CancelledError:
                pass

        if self._gateway_control:
            await self._gateway_control.disconnect()

        if self._bar_consumer:
            await self._bar_consumer.disconnect()

        if self._order_manager:
            await self._order_manager.disconnect()

        if self._db_pool:
            await self._db_pool.disconnect()

        self.logger.info("Strategy runner stopped")

    async def _apply_persisted_state(self) -> None:
        """Apply persisted strategy states from database."""
        if not self._state_repo:
            return

        states = await self._state_repo.get_all()
        state_map = {s.strategy_id: s.enabled for s in states}

        for strategy_id, strategy in self._strategies.items():
            if strategy_id in state_map:
                strategy.enabled = state_map[strategy_id]
                self.logger.info(
                    "Applied persisted state",
                    strategy_id=strategy_id,
                    enabled=strategy.enabled,
                )

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

    async def _control_loop(self) -> None:
        """Listen for control commands and apply them."""
        if not self._control_subscriber or not self._control_supervisor:
            return

        while self._running:
            try:
                async for command in self._control_subscriber.subscribe():
                    if not self._running:
                        break
                    self._handle_control_command(command)
                    self._control_supervisor.reset_errors()
            except asyncio.CancelledError:
                break
            except Exception as e:
                if not await self._control_supervisor.handle_error(e):
                    break

    def _handle_control_command(self, command) -> None:
        """Handle a control command.

        Args:
            command: ControlCommand to process
        """
        strategy = self._strategies.get(command.strategy_id)
        if not strategy:
            self.logger.warning(
                "Control command for unknown strategy",
                strategy_id=command.strategy_id,
            )
            return

        if command.action == "enable":
            strategy.enabled = True
            self.logger.info("Enabled strategy", strategy_id=command.strategy_id)
        elif command.action == "disable":
            strategy.enabled = False
            self.logger.info("Disabled strategy", strategy_id=command.strategy_id)
        else:
            self.logger.warning(
                "Unknown control action",
                action=command.action,
                strategy_id=command.strategy_id,
            )

    async def _run_strategy(
        self,
        loop: asyncio.AbstractEventLoop,
        strategy: BaseStrategy,
        data: BarWithIndicators,
    ) -> tuple[BaseStrategy, Optional[Order]]:
        """Run a strategy synchronously in the event loop.

        Strategy.on_bar is fast pure-python work; dispatching it to a thread pool
        adds ~50us/call of overhead per dispatch. With 5 strategies x millions of
        bars per fulltest, that's the dominant runtime cost. Blocks the event loop
        for the duration of on_bar — acceptable as long as strategies stay fast.
        """
        try:
            order = strategy.on_bar(data)
            return strategy, order
        except Exception as e:
            raise e

    async def _consume_loop(self) -> None:
        """Main loop consuming bars and feeding strategies."""
        if not self._bar_consumer or not self._order_manager or not self._consume_supervisor:
            return

        while self._running:
            try:
                async for bar_data in self._bar_consumer.consume(self._consumer_name):
                    if not self._running:
                        break

                    # Convert to BarWithIndicators (including regime)
                    regime_str = bar_data.get("regime")
                    trend_str = bar_data.get("trend")
                    volatility_str = bar_data.get("volatility")

                    data = BarWithIndicators(
                        bar=bar_data["bar"],
                        sma_20=bar_data.get("sma_20"),
                        rsi_14=bar_data.get("rsi_14"),
                        bb_upper=bar_data.get("bb_upper"),
                        bb_middle=bar_data.get("bb_middle"),
                        bb_lower=bar_data.get("bb_lower"),
                        atr=bar_data.get("atr"),
                        regime=MarketRegime(regime_str) if regime_str else None,
                        trend=MarketTrend(trend_str) if trend_str else None,
                        volatility=VolatilityState(volatility_str) if volatility_str else None,
                        trend_strength=bar_data.get("trend_strength"),
                        volatility_percentile=bar_data.get("volatility_percentile"),
                    )

                    # Update price cache in order manager
                    self._order_manager.update_price(
                        data.symbol, data.close, volume=data.bar.volume
                    )
                    # Advance the broker's simulated clock so fills are
                    # timestamped with the bar time, not wall clock. Lets
                    # fulltest analytics build a real daily equity curve.
                    self._order_manager.set_current_time(data.bar.timestamp)

                    # Reset daily risk counters at day boundaries
                    bar_date = data.bar.timestamp.strftime("%Y-%m-%d")
                    if bar_date != self._current_trading_date:
                        if self._current_trading_date is not None:
                            rm = self._order_manager.risk_manager
                            if rm:
                                rm.reset_daily()
                                self._logged_errors.clear()
                                self.logger.info(
                                    "New trading day, reset daily risk counters",
                                    date=bar_date,
                                )
                        self._current_trading_date = bar_date

                    # Prepare strategy tasks
                    tasks = []
                    loop = asyncio.get_running_loop()

                    for strategy in self._strategies.values():
                        if not strategy.enabled:
                            continue
                        tasks.append(self._run_strategy(loop, strategy, data))

                    if not tasks:
                        continue

                    # Run all strategies in parallel
                    results = await asyncio.gather(*tasks, return_exceptions=True)

                    # Process results
                    for result in results:
                        if isinstance(result, Exception):
                            err_key = str(result)
                            if err_key not in self._logged_errors:
                                self._logged_errors.add(err_key)
                                self.logger.error("Strategy execution error: %s", err_key)
                            continue

                        strategy, order = result
                        if not order:
                            continue

                        # Mark the symbol in-flight before submitting so
                        # at_capacity() sees it immediately — an async
                        # broker (IBKR) can return from submit_order before
                        # the fill lands, and without this a strategy could
                        # fire several entries for the same symbol before
                        # any of them resolve, bypassing max_positions.
                        is_new_entry = (
                            order.side == OrderSide.BUY
                            and strategy.get_position(order.symbol) is None
                        )
                        if is_new_entry:
                            strategy.mark_pending_open(order.symbol)

                        try:
                            self._log_signal(strategy, data, order)
                            await self._order_manager.submit_order(order)

                            # Update local position after fill (in paper mode, immediate)
                            position = await self._order_manager.get_position(
                                strategy.strategy_id, order.symbol
                            )
                            if position:
                                strategy.update_position(position)
                            elif not is_new_entry:
                                # No position and this wasn't a new entry:
                                # the order closed it out — drop the cache.
                                # For a new entry with no position yet (async
                                # broker, fill not landed), clear_position
                                # would also wipe the pending-open marker we
                                # just set; the fill callback resolves it.
                                strategy.clear_position(order.symbol)

                        except Exception as e:
                            strategy.clear_pending_open(order.symbol)
                            err_key = re.sub(r"\$[\d,.]+", "$X", f"{strategy.name}: {e}")
                            if err_key not in self._logged_errors:
                                self._logged_errors.add(err_key)
                                self.logger.warning(
                                    "Order submission rejected: %s - %s",
                                    strategy.name,
                                    str(e),
                                )

                    # Reset errors on successful iteration
                    self._consume_supervisor.reset_errors()

            except asyncio.CancelledError:
                break
            except Exception as e:
                if not await self._consume_supervisor.handle_error(e):
                    break

    def _log_signal(
        self,
        strategy: BaseStrategy,
        data: BarWithIndicators,
        order,
    ) -> None:
        """Log a trading signal."""
        bar = data.bar
        self.logger.info(
            "signal",
            strategy=strategy.name,
            side=order.side.value,
            symbol=bar.symbol,
            price=bar.close,
            rsi_14=round(data.rsi_14, 1) if data.rsi_14 else None,
            sma_20=round(data.sma_20, 2) if data.sma_20 else None,
        )


async def main() -> None:
    """Main entry point."""
    setup_logging(log_name="strategy")
    config = load_config()

    # Create discovery service for standalone mode
    discovery_service: Optional[DiscoveryService] = None
    db_pool: Optional[DatabasePool] = None
    has_discovery_strategy = any(
        s.type == "discovery_momentum" and s.enabled
        for s in config.strategies.enabled
    )
    if has_discovery_strategy:
        db_pool = DatabasePool(config.database)
        await db_pool.connect()
        discovery_service = DiscoveryService(db_pool=db_pool)
        await discovery_service.connect()

    runner = StrategyRunner(config, discovery_service=discovery_service)

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
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run()
