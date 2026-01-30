"""Unit tests for OMS broker implementations."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from axtrade.common import Bar
from axtrade.oms import Fill, Order, OrderSide, OrderStatus, PaperBroker, Position


class TestPaperBroker:
    """Tests for PaperBroker."""

    @pytest.fixture
    def broker(self) -> PaperBroker:
        return PaperBroker(slippage_bps=10)

    @pytest.fixture
    def order(self) -> Order:
        return Order(
            strategy_id="test_strategy",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
        )

    async def test_connect_disconnect(self, broker: PaperBroker) -> None:
        assert broker.connected is False

        await broker.connect()
        assert broker.connected is True

        await broker.disconnect()
        assert broker.connected is False

    async def test_submit_order_requires_connection(
        self, broker: PaperBroker, order: Order
    ) -> None:
        with pytest.raises(RuntimeError, match="not connected"):
            await broker.submit_order(order)

    async def test_submit_order_requires_price(
        self, broker: PaperBroker, order: Order
    ) -> None:
        await broker.connect()

        # No price set, order should be rejected
        broker_id = await broker.submit_order(order)

        assert broker_id == str(order.id)
        assert order.status == OrderStatus.REJECTED

    async def test_submit_buy_order_fills_immediately(
        self, broker: PaperBroker, order: Order
    ) -> None:
        await broker.connect()
        broker.update_price("AAPL", Decimal("185.00"))

        # Track fill via callback
        fills = []
        broker.set_fill_callback(AsyncMock(side_effect=lambda f: fills.append(f)))

        broker_id = await broker.submit_order(order)

        assert broker_id == str(order.id)
        assert order.status == OrderStatus.FILLED
        assert order.filled_quantity == Decimal("100")
        assert len(fills) == 1

    async def test_slippage_applied_on_buy(
        self, broker: PaperBroker, order: Order
    ) -> None:
        await broker.connect()
        broker.update_price("AAPL", Decimal("100.00"))

        await broker.submit_order(order)

        # With 10 bps slippage on buy, price should be higher
        # 100 * (1 + 10/10000) = 100.10
        assert order.avg_fill_price == Decimal("100.10")

    async def test_slippage_applied_on_sell(self, broker: PaperBroker) -> None:
        await broker.connect()
        broker.update_price("AAPL", Decimal("100.00"))

        # First buy to create position
        buy_order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
        )
        await broker.submit_order(buy_order)

        # Now sell
        sell_order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.SELL,
            quantity=Decimal("100"),
        )
        await broker.submit_order(sell_order)

        # With 10 bps slippage on sell, price should be lower
        # 100 / (1 + 10/10000) = 99.90 (approximately)
        assert sell_order.avg_fill_price < Decimal("100.00")

    async def test_buy_creates_position(
        self, broker: PaperBroker, order: Order
    ) -> None:
        await broker.connect()
        broker.update_price("AAPL", Decimal("185.00"))

        await broker.submit_order(order)

        position = broker.get_position("AAPL")
        assert position is not None
        assert position.symbol == "AAPL"
        assert position.side == "long"
        assert position.quantity == Decimal("100")

    async def test_sell_closes_position(self, broker: PaperBroker) -> None:
        await broker.connect()
        broker.update_price("AAPL", Decimal("185.00"))

        # Buy
        buy_order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
        )
        await broker.submit_order(buy_order)

        # Sell same quantity
        sell_order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.SELL,
            quantity=Decimal("100"),
        )
        await broker.submit_order(sell_order)

        assert broker.get_position("AAPL") is None

    async def test_partial_sell_reduces_position(self, broker: PaperBroker) -> None:
        await broker.connect()
        broker.update_price("AAPL", Decimal("185.00"))

        # Buy 100
        buy_order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
        )
        await broker.submit_order(buy_order)

        # Sell 50
        sell_order = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.SELL,
            quantity=Decimal("50"),
        )
        await broker.submit_order(sell_order)

        position = broker.get_position("AAPL")
        assert position is not None
        assert position.quantity == Decimal("50")

    async def test_adding_to_position_updates_avg_price(
        self, broker: PaperBroker
    ) -> None:
        await broker.connect()

        # Buy at 100
        broker.update_price("AAPL", Decimal("100.00"))
        order1 = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
        )
        await broker.submit_order(order1)

        # Buy more at 110
        broker.update_price("AAPL", Decimal("110.00"))
        order2 = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
        )
        await broker.submit_order(order2)

        position = broker.get_position("AAPL")
        assert position.quantity == Decimal("200")
        # Average should be around (100.10 * 100 + 110.11 * 100) / 200 = ~105.105
        assert position.avg_entry_price > Decimal("100") and position.avg_entry_price < Decimal("111")

    async def test_get_positions(self, broker: PaperBroker) -> None:
        await broker.connect()
        broker.update_price("AAPL", Decimal("185.00"))
        broker.update_price("MSFT", Decimal("420.00"))

        # Buy AAPL
        order1 = Order(
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
        )
        await broker.submit_order(order1)

        # Buy MSFT
        order2 = Order(
            strategy_id="test",
            symbol="MSFT",
            side=OrderSide.BUY,
            quantity=Decimal("50"),
        )
        await broker.submit_order(order2)

        positions = await broker.get_positions()
        assert len(positions) == 2
        symbols = {p.symbol for p in positions}
        assert symbols == {"AAPL", "MSFT"}

    async def test_cancel_order_returns_false(
        self, broker: PaperBroker
    ) -> None:
        await broker.connect()

        # Paper orders fill immediately, so cancel always returns false
        result = await broker.cancel_order("some-order-id")
        assert result is False

    async def test_update_price_updates_position_mtm(
        self, broker: PaperBroker, order: Order
    ) -> None:
        await broker.connect()
        broker.update_price("AAPL", Decimal("100.00"))

        await broker.submit_order(order)

        position = broker.get_position("AAPL")
        initial_price = position.current_price

        # Update price
        broker.update_price("AAPL", Decimal("110.00"))

        position = broker.get_position("AAPL")
        assert position.current_price == Decimal("110.00")
        assert position.unrealized_pnl > Decimal("0")

    async def test_fill_callback_invoked(
        self, broker: PaperBroker, order: Order
    ) -> None:
        await broker.connect()
        broker.update_price("AAPL", Decimal("185.00"))

        callback = AsyncMock()
        broker.set_fill_callback(callback)

        await broker.submit_order(order)

        callback.assert_called_once()
        fill = callback.call_args[0][0]
        assert isinstance(fill, Fill)
        assert fill.symbol == "AAPL"
        assert fill.side == OrderSide.BUY
        assert fill.quantity == Decimal("100")

    async def test_fill_includes_commission(
        self, broker: PaperBroker, order: Order
    ) -> None:
        await broker.connect()
        broker.update_price("AAPL", Decimal("185.00"))

        fills = []
        broker.set_fill_callback(AsyncMock(side_effect=lambda f: fills.append(f)))

        await broker.submit_order(order)

        assert len(fills) == 1
        assert fills[0].commission == Decimal("1.00")
