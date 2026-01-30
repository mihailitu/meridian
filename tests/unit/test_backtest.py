"""Unit tests for backtest module."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from axtrade.backtest import (
    BacktestConfig,
    BacktestResult,
    EquityPoint,
    PerformanceAnalyzer,
    SimulatedBroker,
    TradeRecord,
)
from axtrade.common import Bar
from axtrade.oms import Order, OrderSide


class TestTradeRecord:
    """Tests for TradeRecord dataclass."""

    def test_to_dict(self) -> None:
        trade = TradeRecord(
            timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
            side="BUY",
            quantity=Decimal("100"),
            price=Decimal("185.50"),
            commission=Decimal("1.00"),
            pnl=None,
        )
        data = trade.to_dict()

        assert data["side"] == "BUY"
        assert data["quantity"] == "100"
        assert data["price"] == "185.50"
        assert data["pnl"] is None

    def test_to_dict_with_pnl(self) -> None:
        trade = TradeRecord(
            timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
            side="SELL",
            quantity=Decimal("100"),
            price=Decimal("186.50"),
            commission=Decimal("1.00"),
            pnl=Decimal("99.00"),
        )
        data = trade.to_dict()

        assert data["pnl"] == "99.00"


class TestEquityPoint:
    """Tests for EquityPoint dataclass."""

    def test_to_dict(self) -> None:
        point = EquityPoint(
            timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
            equity=Decimal("100500.00"),
            drawdown=Decimal("0.5"),
        )
        data = point.to_dict()

        assert data["equity"] == "100500.00"
        assert data["drawdown"] == "0.5"


class TestBacktestConfig:
    """Tests for BacktestConfig dataclass."""

    def test_defaults(self) -> None:
        config = BacktestConfig(
            strategy_type="momentum",
            strategy_id="test_bt",
            symbol="AAPL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )

        assert config.interval == "1m"
        assert config.initial_capital == Decimal("100000")
        assert config.commission_per_trade == Decimal("1.00")
        assert config.slippage_bps == 5


class TestSimulatedBroker:
    """Tests for SimulatedBroker."""

    @pytest.fixture
    def broker(self) -> SimulatedBroker:
        return SimulatedBroker(
            initial_capital=Decimal("100000"),
            commission=Decimal("1.00"),
            slippage_bps=10,
        )

    @pytest.fixture
    def bar(self) -> Bar:
        return Bar(
            symbol="AAPL",
            open=185.0,
            high=186.0,
            low=184.0,
            close=185.50,
            volume=1000,
            timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
        )

    def test_initial_state(self, broker: SimulatedBroker) -> None:
        assert broker.cash == Decimal("100000")
        assert len(broker.trades) == 0
        assert len(broker.equity_curve) == 0

    def test_buy_order_reduces_cash(self, broker: SimulatedBroker, bar: Bar) -> None:
        order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
        )

        fill = broker.execute_order(order, bar, "test")

        assert fill is not None
        assert broker.cash < Decimal("100000")
        assert len(broker.trades) == 1
        assert broker.trades[0].side == "BUY"

    def test_buy_creates_position(self, broker: SimulatedBroker, bar: Bar) -> None:
        order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
        )

        broker.execute_order(order, bar, "test")

        position = broker.get_position("AAPL")
        assert position is not None
        assert position.quantity == Decimal("100")
        assert position.side == "long"

    def test_slippage_applied(self, broker: SimulatedBroker, bar: Bar) -> None:
        order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
        )

        fill = broker.execute_order(order, bar, "test")

        # With 10 bps slippage on buy, price should be higher than close
        assert fill.price > Decimal(str(bar.close))

    def test_sell_closes_position(self, broker: SimulatedBroker, bar: Bar) -> None:
        # First buy
        buy_order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
        )
        broker.execute_order(buy_order, bar, "test")

        # Then sell
        sell_bar = Bar(
            symbol="AAPL",
            open=186.0,
            high=187.0,
            low=185.5,
            close=186.50,
            volume=1000,
            timestamp=datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc),
        )
        sell_order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.SELL,
            quantity=Decimal("100"),
        )
        broker.execute_order(sell_order, sell_bar, "test")

        assert broker.get_position("AAPL") is None
        assert len(broker.trades) == 2
        assert broker.trades[1].pnl is not None

    def test_sell_without_position_rejected(
        self, broker: SimulatedBroker, bar: Bar
    ) -> None:
        order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.SELL,
            quantity=Decimal("100"),
        )

        fill = broker.execute_order(order, bar, "test")

        assert fill is None

    def test_insufficient_capital_rejected(
        self, broker: SimulatedBroker, bar: Bar
    ) -> None:
        order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("10000"),  # 10000 * 185.50 > 100000
        )

        fill = broker.execute_order(order, bar, "test")

        assert fill is None

    def test_update_equity(self, broker: SimulatedBroker, bar: Bar) -> None:
        broker.update_equity(bar, bar.timestamp)

        assert len(broker.equity_curve) == 1
        assert broker.equity_curve[0].equity == Decimal("100000")
        assert broker.equity_curve[0].drawdown == Decimal("0")

    def test_commission_deducted(self, broker: SimulatedBroker, bar: Bar) -> None:
        initial_cash = broker.cash

        order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
        )
        fill = broker.execute_order(order, bar, "test")

        expected_cost = fill.price * Decimal("100") + Decimal("1.00")
        assert broker.cash == initial_cash - expected_cost


class TestPerformanceAnalyzer:
    """Tests for PerformanceAnalyzer."""

    def test_empty_trades(self) -> None:
        metrics = PerformanceAnalyzer.calculate_metrics(
            trades=[],
            equity_curve=[],
            initial_capital=Decimal("100000"),
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )

        assert metrics["total_trades"] == 0
        assert metrics["win_rate"] == 0.0
        assert metrics["sharpe_ratio"] == 0.0

    def test_win_rate_calculation(self) -> None:
        trades = [
            TradeRecord(
                timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
                side="SELL",
                quantity=Decimal("100"),
                price=Decimal("186.00"),
                commission=Decimal("1.00"),
                pnl=Decimal("50.00"),  # Winner
            ),
            TradeRecord(
                timestamp=datetime(2024, 1, 16, 9, 30, tzinfo=timezone.utc),
                side="SELL",
                quantity=Decimal("100"),
                price=Decimal("184.00"),
                commission=Decimal("1.00"),
                pnl=Decimal("-30.00"),  # Loser
            ),
            TradeRecord(
                timestamp=datetime(2024, 1, 17, 9, 30, tzinfo=timezone.utc),
                side="SELL",
                quantity=Decimal("100"),
                price=Decimal("187.00"),
                commission=Decimal("1.00"),
                pnl=Decimal("80.00"),  # Winner
            ),
        ]

        metrics = PerformanceAnalyzer.calculate_metrics(
            trades=trades,
            equity_curve=[],
            initial_capital=Decimal("100000"),
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )

        assert metrics["total_trades"] == 3
        assert metrics["winning_trades"] == 2
        assert metrics["losing_trades"] == 1
        assert metrics["win_rate"] == pytest.approx(66.67, rel=0.01)

    def test_profit_factor(self) -> None:
        trades = [
            TradeRecord(
                timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
                side="SELL",
                quantity=Decimal("100"),
                price=Decimal("186.00"),
                commission=Decimal("1.00"),
                pnl=Decimal("100.00"),
            ),
            TradeRecord(
                timestamp=datetime(2024, 1, 16, 9, 30, tzinfo=timezone.utc),
                side="SELL",
                quantity=Decimal("100"),
                price=Decimal("184.00"),
                commission=Decimal("1.00"),
                pnl=Decimal("-50.00"),
            ),
        ]

        profit_factor = PerformanceAnalyzer.calculate_profit_factor(trades)

        assert profit_factor == 2.0  # 100 / 50

    def test_profit_factor_no_losses(self) -> None:
        trades = [
            TradeRecord(
                timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
                side="SELL",
                quantity=Decimal("100"),
                price=Decimal("186.00"),
                commission=Decimal("1.00"),
                pnl=Decimal("100.00"),
            ),
        ]

        profit_factor = PerformanceAnalyzer.calculate_profit_factor(trades)

        assert profit_factor == float("inf")

    def test_max_drawdown(self) -> None:
        equity_curve = [
            EquityPoint(
                timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
                equity=Decimal("100000"),
                drawdown=Decimal("0"),
            ),
            EquityPoint(
                timestamp=datetime(2024, 1, 15, 10, 30, tzinfo=timezone.utc),
                equity=Decimal("102000"),
                drawdown=Decimal("0"),
            ),
            EquityPoint(
                timestamp=datetime(2024, 1, 15, 11, 30, tzinfo=timezone.utc),
                equity=Decimal("99000"),
                drawdown=Decimal("2.94"),  # (102000-99000)/102000 * 100
            ),
            EquityPoint(
                timestamp=datetime(2024, 1, 15, 12, 30, tzinfo=timezone.utc),
                equity=Decimal("101000"),
                drawdown=Decimal("0.98"),
            ),
        ]

        max_dd = PerformanceAnalyzer.calculate_max_drawdown(equity_curve)

        assert max_dd == pytest.approx(-2.94, rel=0.01)

    def test_sharpe_ratio_insufficient_data(self) -> None:
        equity_curve = [
            EquityPoint(
                timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
                equity=Decimal("100000"),
                drawdown=Decimal("0"),
            ),
        ]

        sharpe = PerformanceAnalyzer.calculate_sharpe(equity_curve)

        assert sharpe == 0.0


class TestBacktestResult:
    """Tests for BacktestResult dataclass."""

    def test_to_dict(self) -> None:
        config = BacktestConfig(
            strategy_type="momentum",
            strategy_id="test_bt",
            symbol="AAPL",
            start_date=date(2024, 1, 1),
            end_date=date(2024, 1, 31),
        )
        result = BacktestResult(
            config=config,
            trades=[],
            equity_curve=[],
            total_trades=5,
            win_rate=60.0,
            total_return=5.5,
            sharpe_ratio=1.5,
        )

        data = result.to_dict()

        assert data["strategy_type"] == "momentum"
        assert data["symbol"] == "AAPL"
        assert data["total_trades"] == 5
        assert data["win_rate"] == 60.0
