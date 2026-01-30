"""Unit tests for OMS module."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from axtrade.common import DatabaseConfig
from axtrade.oms import (
    Fill,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)


class TestOrder:
    """Tests for Order dataclass."""

    def test_defaults(self) -> None:
        order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
        )

        assert order.order_type == OrderType.MARKET
        assert order.status == OrderStatus.PENDING
        assert order.filled_quantity == Decimal("0")
        assert order.limit_price is None
        assert order.avg_fill_price is None
        assert order.id is not None

    def test_limit_order(self) -> None:
        order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("185.00"),
        )

        assert order.order_type == OrderType.LIMIT
        assert order.limit_price == Decimal("185.00")

    def test_to_dict(self) -> None:
        order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
        )
        data = order.to_dict()

        assert data["symbol"] == "AAPL"
        assert data["side"] == "buy"
        assert data["quantity"] == "100"
        assert data["status"] == "pending"


class TestFill:
    """Tests for Fill dataclass."""

    def test_creation(self) -> None:
        order_id = uuid4()
        fill = Fill(
            order_id=order_id,
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            price=Decimal("185.50"),
            commission=Decimal("1.00"),
        )

        assert fill.order_id == order_id
        assert fill.symbol == "AAPL"
        assert fill.price == Decimal("185.50")
        assert fill.commission == Decimal("1.00")

    def test_to_dict(self) -> None:
        order_id = uuid4()
        fill = Fill(
            order_id=order_id,
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            price=Decimal("185.50"),
        )
        data = fill.to_dict()

        assert data["symbol"] == "AAPL"
        assert data["side"] == "buy"
        assert data["price"] == "185.50"


class TestPosition:
    """Tests for Position dataclass."""

    def test_is_open(self) -> None:
        position = Position(
            strategy_id="test",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("185.0"),
        )

        assert position.is_open is True

        position.quantity = Decimal("0")
        assert position.is_open is False

    def test_is_open_when_closed(self) -> None:
        position = Position(
            strategy_id="test",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("185.0"),
            closed_at=datetime.now(timezone.utc),
        )

        assert position.is_open is False

    def test_market_value(self) -> None:
        position = Position(
            strategy_id="test",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("185.0"),
            current_price=Decimal("190.0"),
        )

        assert position.market_value == Decimal("19000.0")

    def test_market_value_no_price(self) -> None:
        position = Position(
            strategy_id="test",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("185.0"),
        )

        assert position.market_value is None

    def test_calculate_unrealized_pnl_long(self) -> None:
        position = Position(
            strategy_id="test",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("185.0"),
        )

        # Price went up
        pnl = position.calculate_unrealized_pnl(Decimal("190.0"))
        assert pnl == Decimal("500.0")  # (190-185) * 100

        # Price went down
        pnl = position.calculate_unrealized_pnl(Decimal("180.0"))
        assert pnl == Decimal("-500.0")  # (180-185) * 100

    def test_calculate_unrealized_pnl_short(self) -> None:
        position = Position(
            strategy_id="test",
            symbol="AAPL",
            side="short",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("185.0"),
        )

        # Price went down (profit for short)
        pnl = position.calculate_unrealized_pnl(Decimal("180.0"))
        assert pnl == Decimal("500.0")  # (185-180) * 100

        # Price went up (loss for short)
        pnl = position.calculate_unrealized_pnl(Decimal("190.0"))
        assert pnl == Decimal("-500.0")  # (185-190) * 100

    def test_to_dict(self) -> None:
        position = Position(
            strategy_id="test",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("185.0"),
            current_price=Decimal("190.0"),
            unrealized_pnl=Decimal("500.0"),
        )
        data = position.to_dict()

        assert data["symbol"] == "AAPL"
        assert data["side"] == "long"
        assert data["quantity"] == "100"
        assert data["avg_entry_price"] == "185.0"
        assert data["unrealized_pnl"] == "500.0"


class TestOrderSide:
    """Tests for OrderSide enum."""

    def test_values(self) -> None:
        assert OrderSide.BUY.value == "buy"
        assert OrderSide.SELL.value == "sell"


class TestOrderType:
    """Tests for OrderType enum."""

    def test_values(self) -> None:
        assert OrderType.MARKET.value == "market"
        assert OrderType.LIMIT.value == "limit"
        assert OrderType.STOP.value == "stop"


class TestOrderStatus:
    """Tests for OrderStatus enum."""

    def test_values(self) -> None:
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.CANCELLED.value == "cancelled"
        assert OrderStatus.REJECTED.value == "rejected"
