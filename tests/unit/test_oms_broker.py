"""Unit tests for OMS broker implementations."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest

from axtrade.common import Bar
from axtrade.oms import Fill, Order, OrderSide, OrderStatus, PaperBroker, Position
from axtrade.oms.broker import InsufficientCashError, VolumeCapExceededError


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

    async def test_submit_order_without_price_raises(
        self, broker: PaperBroker, order: Order
    ) -> None:
        await broker.connect()

        # No price set and no limit price on the order: broker raises. OrderManager
        # is responsible for catching this and marking the order REJECTED.
        with pytest.raises(RuntimeError, match="No price available"):
            await broker.submit_order(order)

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


class TestPaperBrokerCashCheck:
    """Tests for the initial_cash cash-check path."""

    async def test_cash_is_none_by_default(self) -> None:
        """Legacy behavior: no cash limit when initial_cash isn't set."""
        broker = PaperBroker(slippage_bps=0)
        assert broker.cash is None

    async def test_buy_within_cash_succeeds(self) -> None:
        broker = PaperBroker(slippage_bps=0, initial_cash=Decimal("10000"))
        await broker.connect()
        broker.update_price("AAPL", Decimal("100"))

        order = Order(
            strategy_id="test", symbol="AAPL", side=OrderSide.BUY,
            quantity=Decimal("50"),
        )
        await broker.submit_order(order)

        # Cost = 50 * 100 = $5000, commission = $1 (minimum). Cash = 10000 - 5001 = 4999.
        assert order.status == OrderStatus.FILLED
        assert broker.cash == Decimal("4999.00")

    async def test_buy_exceeding_cash_raises(self) -> None:
        broker = PaperBroker(slippage_bps=0, initial_cash=Decimal("1000"))
        await broker.connect()
        broker.update_price("AAPL", Decimal("100"))

        order = Order(
            strategy_id="test", symbol="AAPL", side=OrderSide.BUY,
            quantity=Decimal("50"),  # Would cost $5001 with commission
        )
        with pytest.raises(InsufficientCashError, match="Need"):
            await broker.submit_order(order)

        # Cash unchanged; order still in submitted state from caller's perspective.
        assert broker.cash == Decimal("1000")

    async def test_sell_credits_cash(self) -> None:
        broker = PaperBroker(slippage_bps=0, initial_cash=Decimal("10000"))
        await broker.connect()
        broker.update_price("AAPL", Decimal("100"))

        # Buy then sell — buy debits, sell credits.
        buy = Order(
            strategy_id="test", symbol="AAPL", side=OrderSide.BUY,
            quantity=Decimal("50"),
        )
        await broker.submit_order(buy)
        cash_after_buy = broker.cash

        # Price went up
        broker.update_price("AAPL", Decimal("120"))
        sell = Order(
            strategy_id="test", symbol="AAPL", side=OrderSide.SELL,
            quantity=Decimal("50"),
        )
        await broker.submit_order(sell)

        # Sell proceeds: 50 * 120 = 6000, minus commission. Cash should jump.
        assert broker.cash > cash_after_buy
        # Round trip: buy -$5001 ($5000 + $1 min commission), sell +$5999
        # ($6000 - $1 min commission). Net = -$5001 + $5999 = +$998.
        # Final cash = $10000 + $998 = $10998.
        assert broker.cash == Decimal("10998.00")

    async def test_unmatched_sell_credits_without_check(self) -> None:
        """Sells don't need cash; they always go through (paper short)."""
        broker = PaperBroker(slippage_bps=0, initial_cash=Decimal("1000"))
        await broker.connect()
        broker.update_price("AAPL", Decimal("100"))

        sell = Order(
            strategy_id="test", symbol="AAPL", side=OrderSide.SELL,
            quantity=Decimal("50"),
        )
        await broker.submit_order(sell)

        # Cash went up by proceeds (no cash check on sells).
        assert broker.cash > Decimal("1000")


class TestPaperBrokerVolumeCap:
    """Tests for the max_volume_participation cap (Audit C3)."""

    async def test_cap_disabled_allows_order_far_exceeding_volume(self) -> None:
        """Default (0.0) is disabled: behavior identical even when quantity
        far exceeds the last known volume."""
        broker = PaperBroker(slippage_bps=0)
        await broker.connect()
        broker.update_price("AAPL", Decimal("100"), volume=Decimal("10"))

        order = Order(
            strategy_id="test", symbol="AAPL", side=OrderSide.BUY,
            quantity=Decimal("1000"),
        )
        await broker.submit_order(order)

        assert order.status == OrderStatus.FILLED

    async def test_buy_over_cap_raises_and_leaves_cash_unchanged(self) -> None:
        broker = PaperBroker(
            slippage_bps=0, initial_cash=Decimal("10000"), max_volume_participation=0.1
        )
        await broker.connect()
        broker.update_price("AAPL", Decimal("100"), volume=Decimal("1000"))

        order = Order(
            strategy_id="test", symbol="AAPL", side=OrderSide.BUY,
            quantity=Decimal("200"),  # cap = 1000 * 0.1 = 100
        )
        with pytest.raises(VolumeCapExceededError, match="AAPL"):
            await broker.submit_order(order)

        assert order.status != OrderStatus.FILLED
        assert broker.cash == Decimal("10000")

    async def test_buy_under_cap_fills_normally(self) -> None:
        broker = PaperBroker(slippage_bps=0, max_volume_participation=0.1)
        await broker.connect()
        broker.update_price("AAPL", Decimal("100"), volume=Decimal("1000"))

        order = Order(
            strategy_id="test", symbol="AAPL", side=OrderSide.BUY,
            quantity=Decimal("50"),  # under cap of 100
        )
        await broker.submit_order(order)

        assert order.status == OrderStatus.FILLED

    async def test_unknown_volume_is_permissive(self) -> None:
        """Cap enabled but no volume ever reported for the symbol: check skipped."""
        broker = PaperBroker(slippage_bps=0, max_volume_participation=0.1)
        await broker.connect()
        broker.update_price("AAPL", Decimal("100"))  # no volume passed

        order = Order(
            strategy_id="test", symbol="AAPL", side=OrderSide.BUY,
            quantity=Decimal("100000"),
        )
        await broker.submit_order(order)

        assert order.status == OrderStatus.FILLED

    async def test_sell_over_cap_also_raises(self) -> None:
        broker = PaperBroker(slippage_bps=0, max_volume_participation=0.1)
        await broker.connect()
        broker.update_price("AAPL", Decimal("100"), volume=Decimal("1000"))

        order = Order(
            strategy_id="test", symbol="AAPL", side=OrderSide.SELL,
            quantity=Decimal("200"),  # cap = 100
        )
        with pytest.raises(VolumeCapExceededError, match="AAPL"):
            await broker.submit_order(order)

        assert order.status != OrderStatus.FILLED
