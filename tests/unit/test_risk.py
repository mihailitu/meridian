"""Unit tests for risk management."""

from decimal import Decimal

import pytest

from axtrade.oms import Order, OrderSide, Position, RiskCheckResult, RiskLimits, RiskManager


class TestRiskLimits:
    """Tests for RiskLimits dataclass."""

    def test_defaults(self) -> None:
        limits = RiskLimits()

        assert limits.max_position_size == 1000
        assert limits.max_position_value == Decimal("50000")
        assert limits.max_order_size == 500
        assert limits.max_daily_loss == Decimal("1000")
        assert limits.max_open_orders == 10

    def test_custom_values(self) -> None:
        limits = RiskLimits(
            max_position_size=500,
            max_position_value=Decimal("25000"),
            max_order_size=200,
            max_daily_loss=Decimal("500"),
            max_open_orders=5,
        )

        assert limits.max_position_size == 500
        assert limits.max_position_value == Decimal("25000")


class TestRiskCheckResult:
    """Tests for RiskCheckResult dataclass."""

    def test_approved(self) -> None:
        result = RiskCheckResult(approved=True)

        assert result.approved is True
        assert result.reason is None

    def test_rejected_with_reason(self) -> None:
        result = RiskCheckResult(approved=False, reason="Order too large")

        assert result.approved is False
        assert result.reason == "Order too large"


class TestRiskManager:
    """Tests for RiskManager."""

    @pytest.fixture
    def limits(self) -> RiskLimits:
        return RiskLimits(
            max_position_size=1000,
            max_position_value=Decimal("50000"),
            max_order_size=500,
            max_daily_loss=Decimal("1000"),
            max_open_orders=5,
        )

    @pytest.fixture
    def manager(self, limits: RiskLimits) -> RiskManager:
        return RiskManager(limits)

    def test_initial_state(self, manager: RiskManager) -> None:
        assert manager.daily_pnl == Decimal("0")
        assert manager.open_order_count == 0

    def test_approve_valid_order(self, manager: RiskManager) -> None:
        order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
        )

        result = manager.check_order(order, None, Decimal("185.00"))

        assert result.approved is True

    def test_reject_order_size_exceeded(self, manager: RiskManager) -> None:
        order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("600"),  # Exceeds max_order_size of 500
        )

        result = manager.check_order(order, None, Decimal("185.00"))

        assert result.approved is False
        assert "exceeds limit" in result.reason

    def test_reject_position_size_exceeded(self, manager: RiskManager) -> None:
        # Existing position of 600 shares
        position = Position(
            strategy_id="test",
            symbol="AAPL",
            side="long",
            quantity=Decimal("600"),
            avg_entry_price=Decimal("180.00"),
        )

        # Order to buy 500 more would result in 1100 shares
        order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("500"),
        )

        result = manager.check_order(order, position, Decimal("185.00"))

        assert result.approved is False
        assert "exceed" in result.reason.lower()

    def test_reject_position_value_exceeded(self, manager: RiskManager) -> None:
        order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("300"),
        )

        # 300 shares * $200 = $60,000 > max of $50,000
        result = manager.check_order(order, None, Decimal("200.00"))

        assert result.approved is False
        assert "value" in result.reason.lower()

    def test_reject_daily_loss_limit(self, manager: RiskManager) -> None:
        # Record a loss exceeding daily limit
        manager.record_pnl(Decimal("-1100"))

        order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
        )

        result = manager.check_order(order, None, Decimal("185.00"))

        assert result.approved is False
        assert "loss limit" in result.reason.lower()

    def test_reject_max_open_orders(self, manager: RiskManager) -> None:
        # Submit 5 orders (max)
        for _ in range(5):
            manager.order_submitted()

        order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
        )

        result = manager.check_order(order, None, Decimal("185.00"))

        assert result.approved is False
        assert "open orders" in result.reason.lower()

    def test_order_completed_decrements_count(self, manager: RiskManager) -> None:
        manager.order_submitted()
        manager.order_submitted()
        assert manager.open_order_count == 2

        manager.order_completed()
        assert manager.open_order_count == 1

    def test_order_completed_floor_at_zero(self, manager: RiskManager) -> None:
        manager.order_completed()  # No orders to complete
        assert manager.open_order_count == 0

    def test_record_pnl(self, manager: RiskManager) -> None:
        manager.record_pnl(Decimal("100"))
        assert manager.daily_pnl == Decimal("100")

        manager.record_pnl(Decimal("-50"))
        assert manager.daily_pnl == Decimal("50")

    def test_reset_daily(self, manager: RiskManager) -> None:
        manager.record_pnl(Decimal("-500"))
        assert manager.daily_pnl == Decimal("-500")

        manager.reset_daily()
        assert manager.daily_pnl == Decimal("0")

    def test_sell_reduces_position(self, manager: RiskManager) -> None:
        """Selling should reduce position size, not increase it."""
        position = Position(
            strategy_id="test",
            symbol="AAPL",
            side="long",
            quantity=Decimal("500"),
            avg_entry_price=Decimal("80.00"),
        )

        order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.SELL,
            quantity=Decimal("200"),
        )

        # After selling 200, position would be 300 shares at $100 = $30,000 < $50,000 limit
        result = manager.check_order(order, position, Decimal("100.00"))

        assert result.approved is True

    def test_approve_order_when_price_zero(self, manager: RiskManager) -> None:
        """Skip value check when price is zero (no price available)."""
        order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
        )

        result = manager.check_order(order, None, Decimal("0"))

        # Should still approve since position size is OK
        assert result.approved is True
