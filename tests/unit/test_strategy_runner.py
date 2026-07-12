"""Unit tests for StrategyRunner.

Tests for strategy loading, bar consumption, and order flow.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from axtrade.common import (
    Bar,
    Config,
    DatabaseConfig,
    LoopSupervisor,
    OMSConfig,
    RedisConfig,
    RiskConfig,
    StrategiesConfig,
    StrategyInstanceConfig,
)
from axtrade.oms.types import Fill, Order, OrderSide, Position
from axtrade.strategies import BarWithIndicators, ControlCommand, StrategyState
from axtrade.strategies.runner import StrategyRunner


class TestStrategyRunner:
    """Tests for StrategyRunner."""

    @pytest.fixture
    def mock_config(self) -> Config:
        """Create a test configuration with strategies enabled."""
        config = Config()
        config.redis = RedisConfig(host="localhost", port=6379)
        config.database = DatabaseConfig()
        config.oms = OMSConfig(
            paper_mode=True,
            slippage_bps=10,
            risk=RiskConfig(),
        )
        config.strategies = StrategiesConfig(
            bar_stream="stream:bars:1m:us",
            consumer_group="strategies",
            control_channel="axtrade:strategy:control",
            enabled=[
                StrategyInstanceConfig(
                    type="momentum",
                    id="momentum_01",
                    enabled=True,
                    config={
                        "rsi_oversold": 40,
                        "rsi_overbought": 70,
                        "position_size": 100,
                    },
                ),
                StrategyInstanceConfig(
                    type="mean_reversion",
                    id="mean_rev_01",
                    enabled=True,
                    config={
                        "std_multiplier": 2.0,
                        "position_size": 50,
                    },
                ),
            ],
        )
        return config

    @pytest.fixture
    def runner(self, mock_config: Config) -> StrategyRunner:
        """Create StrategyRunner instance."""
        return StrategyRunner(mock_config)

    def test_init(self, runner: StrategyRunner, mock_config: Config) -> None:
        """Test runner initialization."""
        assert runner.config == mock_config
        assert runner._running is False
        assert runner._strategies == {}

    def test_load_strategies_from_config(
        self, runner: StrategyRunner, mock_config: Config
    ) -> None:
        """Test strategy instantiation from config."""
        runner._load_strategies()

        assert len(runner._strategies) == 2
        assert "momentum_01" in runner._strategies
        assert "mean_rev_01" in runner._strategies

        momentum = runner._strategies["momentum_01"]
        assert momentum.strategy_id == "momentum_01"
        assert momentum.name == "MomentumBreakout"

    def test_load_strategies_disabled_not_loaded(
        self, runner: StrategyRunner, mock_config: Config
    ) -> None:
        """Test disabled strategies are not loaded."""
        # Disable one strategy
        mock_config.strategies.enabled[1].enabled = False

        runner._load_strategies()

        assert len(runner._strategies) == 1
        assert "momentum_01" in runner._strategies
        assert "mean_rev_01" not in runner._strategies

    def test_load_strategies_unknown_type_skipped(
        self, runner: StrategyRunner, mock_config: Config
    ) -> None:
        """Test unknown strategy type is skipped."""
        mock_config.strategies.enabled.append(
            StrategyInstanceConfig(
                type="unknown_strategy",
                id="unknown_01",
                enabled=True,
            )
        )

        runner._load_strategies()

        assert len(runner._strategies) == 2
        assert "unknown_01" not in runner._strategies

    def test_load_strategies_empty(self, mock_config: Config) -> None:
        """Test loading with no strategies configured."""
        mock_config.strategies.enabled = []
        runner = StrategyRunner(mock_config)

        runner._load_strategies()

        assert len(runner._strategies) == 0

    def test_load_strategies_all_disabled(self, mock_config: Config) -> None:
        """Test loading when every configured strategy has enabled: false.

        Mirrors the phase-3 production config, where all strategies were
        disabled after failing IS/OOS gates: entries are present but none
        should be instantiated, and _load_strategies must not raise.
        """
        for strat_config in mock_config.strategies.enabled:
            strat_config.enabled = False
        runner = StrategyRunner(mock_config)

        runner._load_strategies()

        assert len(runner._strategies) == 0

    async def test_load_positions(self, runner: StrategyRunner) -> None:
        """Test loading existing positions into strategies."""
        runner._load_strategies()

        position = Position(
            strategy_id="momentum_01",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("185.00"),
        )

        mock_order_manager = AsyncMock()
        mock_order_manager.get_open_positions.return_value = [position]

        runner._order_manager = mock_order_manager

        await runner._load_positions()

        # Position should be in strategy
        strategy = runner._strategies["momentum_01"]
        assert strategy.get_position("AAPL") is not None

    async def test_apply_persisted_state(self, runner: StrategyRunner) -> None:
        """Test applying persisted strategy states."""
        runner._load_strategies()

        states = [
            StrategyState(
                strategy_id="momentum_01",
                enabled=False,
                updated_at=datetime.now(timezone.utc),
            )
        ]

        mock_state_repo = AsyncMock()
        mock_state_repo.get_all.return_value = states

        runner._state_repo = mock_state_repo

        await runner._apply_persisted_state()

        # Strategy should be disabled
        assert runner._strategies["momentum_01"].enabled is False
        assert runner._strategies["mean_rev_01"].enabled is True

    def test_handle_control_command_enable(self, runner: StrategyRunner) -> None:
        """Test enable command handling."""
        runner._load_strategies()
        runner._strategies["momentum_01"].enabled = False

        command = ControlCommand(
            action="enable",
            strategy_id="momentum_01",
            timestamp=datetime.now(timezone.utc),
        )

        runner._handle_control_command(command)

        assert runner._strategies["momentum_01"].enabled is True

    def test_handle_control_command_disable(self, runner: StrategyRunner) -> None:
        """Test disable command handling."""
        runner._load_strategies()

        command = ControlCommand(
            action="disable",
            strategy_id="momentum_01",
            timestamp=datetime.now(timezone.utc),
        )

        runner._handle_control_command(command)

        assert runner._strategies["momentum_01"].enabled is False

    def test_handle_control_command_unknown_strategy(
        self, runner: StrategyRunner
    ) -> None:
        """Test control command for unknown strategy is ignored."""
        runner._load_strategies()

        command = ControlCommand(
            action="enable",
            strategy_id="unknown_strategy",
            timestamp=datetime.now(timezone.utc),
        )

        # Should not raise
        runner._handle_control_command(command)

    def test_handle_control_command_unknown_action(
        self, runner: StrategyRunner
    ) -> None:
        """Test unknown action is ignored."""
        runner._load_strategies()

        command = ControlCommand(
            action="restart",
            strategy_id="momentum_01",
            timestamp=datetime.now(timezone.utc),
        )

        # Should not raise
        runner._handle_control_command(command)
        # Strategy should still be enabled (unchanged)
        assert runner._strategies["momentum_01"].enabled is True

    async def test_start_initializes_components(
        self, runner: StrategyRunner, mock_config: Config
    ) -> None:
        """Test start initializes database, order manager, etc."""
        mock_pool = AsyncMock()
        mock_order_manager = AsyncMock()
        mock_order_manager.get_open_positions.return_value = []
        mock_bar_consumer = MagicMock()
        mock_state_repo = AsyncMock()
        mock_state_repo.get_all.return_value = []
        mock_control_subscriber = MagicMock()

        # Create async generator for bar consumer that exits immediately
        async def quick_consume(consumer_name):
            runner._running = False
            return
            yield  # Make it a generator

        mock_bar_consumer.connect = AsyncMock()
        mock_bar_consumer.disconnect = AsyncMock()
        mock_bar_consumer.consume.return_value = quick_consume("test")

        # Create async generator for control subscriber
        async def empty_subscribe():
            return
            yield

        mock_control_subscriber.connect = AsyncMock()
        mock_control_subscriber.disconnect = AsyncMock()
        mock_control_subscriber.subscribe.return_value = empty_subscribe()

        with patch("axtrade.strategies.runner.DatabasePool", return_value=mock_pool):
            with patch(
                "axtrade.strategies.runner.OrderManager", return_value=mock_order_manager
            ):
                with patch(
                    "axtrade.strategies.runner.BarConsumer", return_value=mock_bar_consumer
                ):
                    with patch(
                        "axtrade.strategies.runner.StrategyStateRepository",
                        return_value=mock_state_repo,
                    ):
                        with patch(
                            "axtrade.strategies.runner.StrategyControlSubscriber",
                            return_value=mock_control_subscriber,
                        ):
                            await runner.start()

        mock_pool.connect.assert_called_once()
        mock_order_manager.connect.assert_called_once()
        mock_bar_consumer.connect.assert_called_once()
        # Async fill routing (Audit P1-1b) is wired up right after connect.
        mock_order_manager.on_fill.assert_called_once_with(runner._on_order_manager_fill)

    async def test_stop_disconnects_components(
        self, runner: StrategyRunner
    ) -> None:
        """Test stop disconnects all components."""
        import asyncio

        mock_pool = AsyncMock()
        mock_order_manager = AsyncMock()
        mock_bar_consumer = AsyncMock()
        mock_control_subscriber = AsyncMock()

        # Create a real task that we can cancel
        async def dummy_control_loop():
            while True:
                await asyncio.sleep(1)

        mock_control_task = asyncio.create_task(dummy_control_loop())

        runner._db_pool = mock_pool
        runner._order_manager = mock_order_manager
        runner._bar_consumer = mock_bar_consumer
        runner._control_subscriber = mock_control_subscriber
        runner._control_task = mock_control_task
        runner._running = True

        await runner.stop()

        assert runner._running is False
        assert mock_control_task.cancelled()
        mock_control_subscriber.disconnect.assert_called_once()
        mock_bar_consumer.disconnect.assert_called_once()
        mock_order_manager.disconnect.assert_called_once()
        mock_pool.disconnect.assert_called_once()


class TestStrategyRunnerBarProcessing:
    """Tests for bar processing and order submission."""

    @pytest.fixture
    def mock_config(self) -> Config:
        """Create a test configuration."""
        config = Config()
        config.redis = RedisConfig()
        config.database = DatabaseConfig()
        config.oms = OMSConfig(paper_mode=True)
        config.strategies = StrategiesConfig(
            enabled=[
                StrategyInstanceConfig(
                    type="momentum",
                    id="momentum_01",
                    enabled=True,
                    config={
                        "rsi_oversold": 40,
                        "rsi_overbought": 70,
                        "position_size": 100,
                    },
                ),
            ],
        )
        return config

    @pytest.fixture
    def runner(self, mock_config: Config) -> StrategyRunner:
        """Create StrategyRunner instance with loaded strategies."""
        runner = StrategyRunner(mock_config)
        runner._load_strategies()
        return runner

    @pytest.fixture
    def sample_bar(self) -> Bar:
        """Create a sample bar."""
        return Bar(
            symbol="AAPL",
            open=185.0,
            high=186.0,
            low=184.0,
            close=185.50,
            volume=10000,
            timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
        )

    async def test_consume_loop_processes_bars(
        self, runner: StrategyRunner, sample_bar: Bar
    ) -> None:
        """Test bar consumption triggers strategy processing."""
        mock_order_manager = AsyncMock()
        mock_order_manager.submit_order.return_value = uuid4()
        mock_order_manager.get_position.return_value = None

        runner._order_manager = mock_order_manager
        runner._consume_supervisor = LoopSupervisor(name="test", base_delay=0.001)
        runner._running = True

        # Seed momentum's prev_rsi below the cross level so the second bar
        # produces an RSI cross-up entry.
        runner._strategies["momentum_01"]._prev_rsi["AAPL"] = 45.0

        # Create async generator that yields one bar then stops.
        # Momentum entry needs trending regime + RSI crossing 50 + price > SMA.
        bar_data = {
            "bar": sample_bar,
            "sma_20": 184.0,
            "rsi_14": 55.0,
            "regime": "trending_up",
            "trend": "bullish",
            "trend_strength": 60.0,
        }

        async def consume_one(consumer_name):
            yield bar_data
            runner._running = False

        mock_bar_consumer = MagicMock()
        mock_bar_consumer.consume.return_value = consume_one("test")

        runner._bar_consumer = mock_bar_consumer

        await runner._consume_loop()

        # Order should be submitted (momentum buy signal)
        mock_order_manager.submit_order.assert_called_once()
        order = mock_order_manager.submit_order.call_args[0][0]
        assert order.side == OrderSide.BUY
        assert order.symbol == "AAPL"

    async def test_consume_loop_updates_price(
        self, runner: StrategyRunner, sample_bar: Bar
    ) -> None:
        """Test bar processing updates order manager price cache."""
        mock_order_manager = MagicMock()
        mock_order_manager.submit_order = AsyncMock()
        mock_order_manager.get_position = AsyncMock(return_value=None)

        runner._order_manager = mock_order_manager
        runner._consume_supervisor = LoopSupervisor(name="test", base_delay=0.001)
        runner._running = True

        bar_data = {
            "bar": sample_bar,
            "sma_20": 190.0,  # No signal
            "rsi_14": 50.0,
        }

        async def consume_one(consumer_name):
            yield bar_data
            runner._running = False

        mock_bar_consumer = MagicMock()
        mock_bar_consumer.consume.return_value = consume_one("test")

        runner._bar_consumer = mock_bar_consumer

        await runner._consume_loop()

        mock_order_manager.update_price.assert_called_with("AAPL", 185.5, volume=10000)

    async def test_consume_loop_disabled_strategy_skipped(
        self, runner: StrategyRunner, sample_bar: Bar
    ) -> None:
        """Test disabled strategies don't process bars."""
        runner._strategies["momentum_01"].enabled = False
        runner._strategies["momentum_01"]._prev_rsi["AAPL"] = 45.0

        mock_order_manager = MagicMock()
        mock_order_manager.submit_order = AsyncMock()
        mock_order_manager.get_position = AsyncMock(return_value=None)

        runner._order_manager = mock_order_manager
        runner._consume_supervisor = LoopSupervisor(name="test", base_delay=0.001)
        runner._running = True

        bar_data = {
            "bar": sample_bar,
            "sma_20": 184.0,
            "rsi_14": 55.0,  # Would trigger buy signal if enabled
            "regime": "trending_up",
            "trend_strength": 60.0,
        }

        async def consume_one(consumer_name):
            yield bar_data
            runner._running = False

        mock_bar_consumer = MagicMock()
        mock_bar_consumer.consume.return_value = consume_one("test")

        runner._bar_consumer = mock_bar_consumer

        await runner._consume_loop()

        # No order should be submitted
        mock_order_manager.submit_order.assert_not_called()

    async def test_consume_loop_position_synced_after_fill(
        self, runner: StrategyRunner, sample_bar: Bar
    ) -> None:
        """Test position is synced to strategy after order."""
        position = Position(
            strategy_id="momentum_01",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("185.50"),
        )

        mock_order_manager = MagicMock()
        mock_order_manager.submit_order = AsyncMock(return_value=uuid4())
        mock_order_manager.get_position = AsyncMock(return_value=position)

        runner._order_manager = mock_order_manager
        runner._consume_supervisor = LoopSupervisor(name="test", base_delay=0.001)
        runner._running = True
        runner._strategies["momentum_01"]._prev_rsi["AAPL"] = 45.0

        bar_data = {
            "bar": sample_bar,
            "sma_20": 184.0,
            "rsi_14": 55.0,
            "regime": "trending_up",
            "trend_strength": 60.0,
        }

        async def consume_one(consumer_name):
            yield bar_data
            runner._running = False

        mock_bar_consumer = MagicMock()
        mock_bar_consumer.consume.return_value = consume_one("test")

        runner._bar_consumer = mock_bar_consumer

        await runner._consume_loop()

        # Position should be fetched and updated in strategy
        mock_order_manager.get_position.assert_called_with("momentum_01", "AAPL")
        strategy_position = runner._strategies["momentum_01"].get_position("AAPL")
        assert strategy_position is not None

    async def test_consume_loop_clears_position_after_close(
        self, runner: StrategyRunner, sample_bar: Bar
    ) -> None:
        """Test position is cleared in strategy when None after order."""
        # Set up existing position in strategy
        existing_position = Position(
            strategy_id="momentum_01",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("180.00"),
        )
        runner._strategies["momentum_01"].update_position(existing_position)

        # Mock order manager returns None (position closed)
        mock_order_manager = MagicMock()
        mock_order_manager.submit_order = AsyncMock(return_value=uuid4())
        mock_order_manager.get_position = AsyncMock(return_value=None)

        runner._order_manager = mock_order_manager
        runner._consume_supervisor = LoopSupervisor(name="test", base_delay=0.001)
        runner._running = True

        # Bar that would trigger sell signal (overbought)
        bar_data = {
            "bar": sample_bar,
            "sma_20": 184.0,
            "rsi_14": 75.0,  # Overbought with position = sell
            "regime": "trending_up",
            "trend_strength": 60.0,
        }

        async def consume_one(consumer_name):
            yield bar_data
            runner._running = False

        mock_bar_consumer = MagicMock()
        mock_bar_consumer.consume.return_value = consume_one("test")

        runner._bar_consumer = mock_bar_consumer

        await runner._consume_loop()

        # Position should be cleared
        assert runner._strategies["momentum_01"].get_position("AAPL") is None

    async def test_consume_loop_strategy_error_handled(
        self, runner: StrategyRunner, sample_bar: Bar
    ) -> None:
        """Test strategy errors are caught and logged."""
        mock_order_manager = MagicMock()
        mock_order_manager.submit_order = AsyncMock(side_effect=Exception("Test error"))
        mock_order_manager.get_position = AsyncMock(return_value=None)

        runner._order_manager = mock_order_manager
        runner._consume_supervisor = LoopSupervisor(name="test", base_delay=0.001)
        runner._running = True
        runner._strategies["momentum_01"]._prev_rsi["AAPL"] = 45.0

        bar_data = {
            "bar": sample_bar,
            "sma_20": 184.0,
            "rsi_14": 55.0,  # Buy signal
            "regime": "trending_up",
            "trend_strength": 60.0,
        }

        async def consume_one(consumer_name):
            yield bar_data
            runner._running = False

        mock_bar_consumer = MagicMock()
        mock_bar_consumer.consume.return_value = consume_one("test")

        runner._bar_consumer = mock_bar_consumer

        # Should not raise
        await runner._consume_loop()

    def test_log_signal(self, runner: StrategyRunner, sample_bar: Bar) -> None:
        """Test signal logging."""
        strategy = runner._strategies["momentum_01"]
        data = BarWithIndicators(
            bar=sample_bar,
            sma_20=184.0,
            rsi_14=35.0,
        )

        order = Order(
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
        )

        # Should not raise
        runner._log_signal(strategy, data, order)


class TestStrategyRunnerFillRouting:
    """Tests for the async fill-routing callback registered with
    OrderManager (Audit P1-1). This is what makes fill handling correct for
    async brokers (IBKR): unlike the post-submit poll in _consume_loop,
    which only catches fills that already landed by the time submit_order
    returns, this callback fires whenever OrderManager resolves a fill,
    however late."""

    @pytest.fixture
    def mock_config(self) -> Config:
        config = Config()
        config.redis = RedisConfig()
        config.database = DatabaseConfig()
        config.oms = OMSConfig(paper_mode=True)
        config.strategies = StrategiesConfig(
            enabled=[
                StrategyInstanceConfig(
                    type="momentum",
                    id="momentum_01",
                    enabled=True,
                    config={
                        "rsi_oversold": 40,
                        "rsi_overbought": 70,
                        "position_size": 100,
                    },
                ),
            ],
        )
        return config

    @pytest.fixture
    def runner(self, mock_config: Config) -> StrategyRunner:
        runner = StrategyRunner(mock_config)
        runner._load_strategies()
        return runner

    async def test_fill_routes_to_matching_strategy(self, runner: StrategyRunner) -> None:
        position = Position(
            strategy_id="momentum_01",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("185.00"),
        )
        mock_order_manager = AsyncMock()
        mock_order_manager.get_position.return_value = position
        runner._order_manager = mock_order_manager

        strategy = runner._strategies["momentum_01"]
        fill_calls = []
        strategy.on_fill = lambda f: fill_calls.append(f)

        fill = Fill(
            order_id=uuid4(),
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            price=Decimal("185.00"),
        )

        await runner._on_order_manager_fill(fill)

        mock_order_manager.get_position.assert_called_once_with("momentum_01", "AAPL")
        assert strategy.get_position("AAPL") is position
        assert fill_calls == [fill]

    async def test_fill_clears_position_when_none(self, runner: StrategyRunner) -> None:
        """A closing fill: get_position comes back None (position fully
        closed), so the strategy's cached position must be cleared."""
        strategy = runner._strategies["momentum_01"]
        strategy.update_position(
            Position(
                strategy_id="momentum_01",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("180.00"),
            )
        )

        mock_order_manager = AsyncMock()
        mock_order_manager.get_position.return_value = None
        runner._order_manager = mock_order_manager

        fill = Fill(
            order_id=uuid4(),
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.SELL,
            quantity=Decimal("100"),
            price=Decimal("190.00"),
        )

        await runner._on_order_manager_fill(fill)

        assert strategy.get_position("AAPL") is None

    async def test_unknown_strategy_id_ignored(self, runner: StrategyRunner) -> None:
        """A fill for a strategy_id this runner doesn't know about (e.g.
        from a stale/previous config) must be dropped, not raise."""
        mock_order_manager = AsyncMock()
        runner._order_manager = mock_order_manager

        fill = Fill(
            order_id=uuid4(),
            strategy_id="unknown_strategy",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            price=Decimal("185.00"),
        )

        # Should not raise
        await runner._on_order_manager_fill(fill)

        mock_order_manager.get_position.assert_not_called()

    async def test_on_fill_error_is_caught(self, runner: StrategyRunner) -> None:
        mock_order_manager = AsyncMock()
        mock_order_manager.get_position.return_value = None
        runner._order_manager = mock_order_manager

        strategy = runner._strategies["momentum_01"]

        def bad_on_fill(f):
            raise ValueError("boom")

        strategy.on_fill = bad_on_fill

        fill = Fill(
            order_id=uuid4(),
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            price=Decimal("185.00"),
        )

        # Should not raise
        await runner._on_order_manager_fill(fill)


class TestStrategyRunnerPendingOpens:
    """Integration tests for in-flight entry tracking around order
    submission in _consume_loop (Audit P1-1c): the per-strategy
    max_positions cap can't be bypassed by orders whose fills haven't
    landed yet."""

    @pytest.fixture
    def mock_config(self) -> Config:
        config = Config()
        config.redis = RedisConfig()
        config.database = DatabaseConfig()
        config.oms = OMSConfig(paper_mode=True)
        config.strategies = StrategiesConfig(
            enabled=[
                StrategyInstanceConfig(
                    type="momentum",
                    id="momentum_01",
                    enabled=True,
                    config={
                        "rsi_oversold": 40,
                        "rsi_overbought": 70,
                        "position_size": 100,
                        "max_positions": 1,
                    },
                ),
            ],
        )
        return config

    @pytest.fixture
    def runner(self, mock_config: Config) -> StrategyRunner:
        runner = StrategyRunner(mock_config)
        runner._load_strategies()
        return runner

    @pytest.fixture
    def sample_bar(self) -> Bar:
        return Bar(
            symbol="AAPL",
            open=185.0,
            high=186.0,
            low=184.0,
            close=185.50,
            volume=10000,
            timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
        )

    @staticmethod
    def _buy_bar_data(sample_bar: Bar) -> dict:
        return {
            "bar": sample_bar,
            "sma_20": 184.0,
            "rsi_14": 55.0,
            "regime": "trending_up",
            "trend_strength": 60.0,
        }

    async def test_symbol_marked_pending_before_submit_and_cleared_by_fill(
        self, runner: StrategyRunner, sample_bar: Bar
    ) -> None:
        strategy = runner._strategies["momentum_01"]
        strategy._prev_rsi["AAPL"] = 45.0  # seed cross-up condition

        observed_at_capacity_during_submit = []

        async def submit_and_observe(order):
            # By the time submit_order is awaited, the symbol must already
            # be marked pending and counted by at_capacity() — this is what
            # closes the async-broker window where an IBKR submit_order
            # returns before any fill lands.
            observed_at_capacity_during_submit.append(strategy.at_capacity())
            return uuid4()

        position = Position(
            strategy_id="momentum_01",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("185.50"),
        )

        mock_order_manager = MagicMock()
        mock_order_manager.submit_order = AsyncMock(side_effect=submit_and_observe)
        mock_order_manager.get_position = AsyncMock(return_value=position)

        runner._order_manager = mock_order_manager
        runner._consume_supervisor = LoopSupervisor(name="test", base_delay=0.001)
        runner._running = True

        async def consume_one(consumer_name):
            yield self._buy_bar_data(sample_bar)
            runner._running = False

        mock_bar_consumer = MagicMock()
        mock_bar_consumer.consume.return_value = consume_one("test")
        runner._bar_consumer = mock_bar_consumer

        await runner._consume_loop()

        assert observed_at_capacity_during_submit == [True]
        # Fill landed synchronously (paper-mode fast path): the pending
        # marker must be cleared, with the settled position now carrying
        # capacity instead.
        assert "AAPL" not in strategy._pending_opens
        assert strategy.at_capacity() is True

    async def test_rejection_clears_pending_and_restores_capacity(
        self, runner: StrategyRunner, sample_bar: Bar
    ) -> None:
        strategy = runner._strategies["momentum_01"]
        strategy._prev_rsi["AAPL"] = 45.0

        mock_order_manager = MagicMock()
        mock_order_manager.submit_order = AsyncMock(side_effect=Exception("rejected"))
        mock_order_manager.get_position = AsyncMock(return_value=None)

        runner._order_manager = mock_order_manager
        runner._consume_supervisor = LoopSupervisor(name="test", base_delay=0.001)
        runner._running = True

        async def consume_one(consumer_name):
            yield self._buy_bar_data(sample_bar)
            runner._running = False

        mock_bar_consumer = MagicMock()
        mock_bar_consumer.consume.return_value = consume_one("test")
        runner._bar_consumer = mock_bar_consumer

        # Should not raise (existing error-handling path)
        await runner._consume_loop()

        assert "AAPL" not in strategy._pending_opens
        assert strategy.at_capacity() is False

    async def test_async_broker_pending_survives_post_submit_poll(
        self, runner: StrategyRunner, sample_bar: Bar
    ) -> None:
        """Async-broker case: submit_order returns before the fill lands, so
        the post-submit poll sees no position. The poll must NOT clear the
        pending-open marker (clear_position would discard it) — the fill
        callback is what resolves it later. Regression for the review find
        on audit P1-1c."""
        strategy = runner._strategies["momentum_01"]
        strategy._prev_rsi["AAPL"] = 45.0

        mock_order_manager = MagicMock()
        mock_order_manager.submit_order = AsyncMock(return_value=uuid4())
        # Fill has not landed: position is not visible yet.
        mock_order_manager.get_position = AsyncMock(return_value=None)

        runner._order_manager = mock_order_manager
        runner._consume_supervisor = LoopSupervisor(name="test", base_delay=0.001)
        runner._running = True

        async def consume_one(consumer_name):
            yield self._buy_bar_data(sample_bar)
            runner._running = False

        mock_bar_consumer = MagicMock()
        mock_bar_consumer.consume.return_value = consume_one("test")
        runner._bar_consumer = mock_bar_consumer

        await runner._consume_loop()

        # The entry is still in flight: pending marker intact, capacity held.
        assert "AAPL" in strategy._pending_opens
        assert strategy.at_capacity() is True


class TestStrategyStateRepository:
    """Tests for StrategyStateRepository."""

    @pytest.fixture
    def mock_pool(self) -> MagicMock:
        """Create a mock database pool."""
        pool = MagicMock()
        pool.acquire = MagicMock()
        return pool

    @pytest.fixture
    def repo(self, mock_pool: MagicMock):
        """Create StrategyStateRepository with mock pool."""
        from axtrade.strategies.control import StrategyStateRepository

        return StrategyStateRepository(mock_pool)

    async def test_get_state(self, repo, mock_pool: MagicMock) -> None:
        """Test getting strategy state."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        now = datetime.now(timezone.utc)
        mock_conn.fetchrow.return_value = {
            "strategy_id": "momentum_01",
            "enabled": True,
            "updated_at": now,
        }

        result = await repo.get("momentum_01")

        assert result is not None
        assert result.strategy_id == "momentum_01"
        assert result.enabled is True

    async def test_get_state_not_found(self, repo, mock_pool: MagicMock) -> None:
        """Test get returns None for non-existent state."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_conn.fetchrow.return_value = None

        result = await repo.get("unknown")

        assert result is None

    async def test_get_all_states(self, repo, mock_pool: MagicMock) -> None:
        """Test getting all strategy states."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        now = datetime.now(timezone.utc)
        mock_conn.fetch.return_value = [
            {"strategy_id": "momentum_01", "enabled": True, "updated_at": now},
            {"strategy_id": "mean_rev_01", "enabled": False, "updated_at": now},
        ]

        result = await repo.get_all()

        assert len(result) == 2
        assert result[0].strategy_id == "momentum_01"
        assert result[1].enabled is False

    async def test_set_state(self, repo, mock_pool: MagicMock) -> None:
        """Test setting strategy state."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn

        now = datetime.now(timezone.utc)
        mock_conn.fetchrow.return_value = {
            "strategy_id": "momentum_01",
            "enabled": False,
            "updated_at": now,
        }

        result = await repo.set_state("momentum_01", False)

        assert result.strategy_id == "momentum_01"
        assert result.enabled is False
        args = mock_conn.fetchrow.call_args[0]
        assert "ON CONFLICT" in args[0]

    async def test_delete_state(self, repo, mock_pool: MagicMock) -> None:
        """Test deleting strategy state."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_conn.execute.return_value = "DELETE 1"

        result = await repo.delete("momentum_01")

        assert result is True

    async def test_delete_state_not_found(self, repo, mock_pool: MagicMock) -> None:
        """Test delete returns False when not found."""
        mock_conn = AsyncMock()
        mock_pool.acquire.return_value.__aenter__.return_value = mock_conn
        mock_conn.execute.return_value = "DELETE 0"

        result = await repo.delete("unknown")

        assert result is False
