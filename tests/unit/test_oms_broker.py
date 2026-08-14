"""Unit tests for OMS broker implementations."""

import asyncio
import sys
import types
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from axtrade.common import Bar, IBKRConfig
from axtrade.oms import Fill, Order, OrderSide, OrderStatus, OrderType, PaperBroker, Position
from axtrade.oms.broker import IBKRBroker, InsufficientCashError, VolumeCapExceededError


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


class TestPaperBrokerTerminalCallback:
    """Tests for PaperBroker.set_terminal_callback (Audit P1-4).

    PaperBroker resolves every order synchronously inside submit_order and
    never holds a resting order, so there is no broker-side terminal
    transition to report — the callback is stored for protocol conformance
    but never fired.
    """

    async def test_set_terminal_callback_stores_but_never_fires(self) -> None:
        broker = PaperBroker(slippage_bps=0)
        await broker.connect()
        broker.update_price("AAPL", Decimal("100"))

        calls = []

        async def terminal_cb(order_id, status):
            calls.append((order_id, status))

        broker.set_terminal_callback(terminal_cb)
        assert broker._terminal_callback is terminal_cb

        order = Order(
            strategy_id="test", symbol="AAPL", side=OrderSide.BUY, quantity=Decimal("10"),
        )
        await broker.submit_order(order)
        await broker.cancel_order(str(order.id))

        assert calls == []


def _fake_trade(order_id: int, status: str):
    """Minimal ib_insync-shaped stand-in for _on_order_status tests."""

    class _OrderStatus:
        def __init__(self, status: str) -> None:
            self.status = status

    class _IBOrder:
        def __init__(self, order_id: int) -> None:
            self.orderId = order_id

    class _Trade:
        def __init__(self, order_id: int, status: str) -> None:
            self.order = _IBOrder(order_id)
            self.orderStatus = _OrderStatus(status)

    return _Trade(order_id, status)


class TestIBKRBrokerTerminalCallback:
    """Tests for IBKRBroker terminal-callback propagation (Audit P1-4).

    _on_order_status is a plain sync ib_insync event handler; it can be
    exercised directly without a live TWS/Gateway connection by seeding
    _order_map and feeding it a fake Trade object.
    """

    @pytest.fixture
    def broker(self) -> IBKRBroker:
        return IBKRBroker(IBKRConfig())

    async def test_cancelled_status_fires_terminal_callback(self, broker: IBKRBroker) -> None:
        our_id = uuid4()
        broker._order_map[7] = (our_id, "momentum_01")
        calls = []

        async def terminal_cb(order_id, status):
            calls.append((order_id, status))

        broker.set_terminal_callback(terminal_cb)

        broker._on_order_status(_fake_trade(7, "Cancelled"))
        await asyncio.gather(*broker._pending_callbacks)

        assert calls == [(our_id, OrderStatus.CANCELLED)]

    @pytest.mark.parametrize("status", ["ApiCancelled", "Inactive"])
    async def test_other_terminal_statuses_also_fire(
        self, broker: IBKRBroker, status: str
    ) -> None:
        our_id = uuid4()
        broker._order_map[7] = (our_id, "momentum_01")
        calls = []

        async def terminal_cb(order_id, order_status):
            calls.append((order_id, order_status))

        broker.set_terminal_callback(terminal_cb)

        broker._on_order_status(_fake_trade(7, status))
        await asyncio.gather(*broker._pending_callbacks)

        assert calls == [(our_id, OrderStatus.CANCELLED)]

    async def test_unknown_order_id_ignored(self, broker: IBKRBroker) -> None:
        calls = []

        async def terminal_cb(order_id, status):
            calls.append((order_id, status))

        broker.set_terminal_callback(terminal_cb)

        # Should not raise; no order_map entry for this ibkr id.
        broker._on_order_status(_fake_trade(999, "Cancelled"))

        assert calls == []
        assert broker._pending_callbacks == []

    async def test_non_terminal_status_ignored(self, broker: IBKRBroker) -> None:
        our_id = uuid4()
        broker._order_map[7] = (our_id, "momentum_01")
        calls = []

        async def terminal_cb(order_id, status):
            calls.append((order_id, status))

        broker.set_terminal_callback(terminal_cb)

        broker._on_order_status(_fake_trade(7, "Submitted"))

        assert calls == []
        assert broker._pending_callbacks == []

    async def test_no_terminal_callback_set_does_not_raise(self, broker: IBKRBroker) -> None:
        broker._order_map[7] = (uuid4(), "momentum_01")

        # No set_terminal_callback call at all — must not raise.
        broker._on_order_status(_fake_trade(7, "Cancelled"))
        assert broker._pending_callbacks == []


class _FakeIB:
    """Minimal stand-in for ib_insync.IB, enough to exercise cancel_order."""

    def __init__(self, trades: list) -> None:
        self._trades = trades
        self.cancelled: list = []

    def isConnected(self) -> bool:
        return True

    def openTrades(self) -> list:
        return self._trades

    def cancelOrder(self, order) -> None:
        self.cancelled.append(order)


class TestIBKRBrokerCancelOrder:
    """Tests for IBKRBroker.cancel_order (Audit P1-4)."""

    @pytest.fixture
    def broker(self) -> IBKRBroker:
        return IBKRBroker(IBKRConfig())

    async def test_cancel_known_order_requests_cancel_and_returns_true(
        self, broker: IBKRBroker
    ) -> None:
        trade = _fake_trade(7, "Submitted")
        broker._ib = _FakeIB([trade])

        result = await broker.cancel_order("7")

        assert result is True
        assert broker._ib.cancelled == [trade.order]

    async def test_cancel_unknown_order_returns_false(self, broker: IBKRBroker) -> None:
        broker._ib = _FakeIB([])

        result = await broker.cancel_order("999")

        assert result is False

    async def test_cancel_when_not_connected_returns_false(self, broker: IBKRBroker) -> None:
        # broker._ib is None until connect() runs.
        result = await broker.cancel_order("7")
        assert result is False


class _FakeConnectIB:
    """Minimal fake ib_insync.IB for exercising IBKRBroker.connect() (D3).

    ib_insync can't actually be imported in this environment (eventkit's
    module-level asyncio.get_event_loop() call is incompatible with the
    installed Python), so connect()'s local `from ib_insync import IB` is
    redirected via sys.modules rather than patched directly.
    """

    def __init__(self):
        self.connect_kwargs: dict | None = None
        self.orderStatusEvent = MagicMock()
        self.execDetailsEvent = MagicMock()
        self.disconnectedEvent = MagicMock()

    async def connectAsync(self, host, port, clientId):
        self.connect_kwargs = {"host": host, "port": port, "clientId": clientId}


def _install_fake_ib_insync(monkeypatch, fake_ib_instance) -> None:
    """Install a fake `ib_insync` module so `from ib_insync import IB` inside
    connect() resolves to a stand-in instead of the real (unimportable)
    package."""
    fake_module = types.ModuleType("ib_insync")
    fake_module.IB = lambda: fake_ib_instance
    monkeypatch.setitem(sys.modules, "ib_insync", fake_module)


class TestIBKRBrokerLivePortGuard:
    """Tests for IBKRBroker.connect() refusing live ports (7496 TWS / 4001
    IB Gateway) unless oms.ibkr_allow_live is explicitly set (D3)."""

    @pytest.mark.parametrize("port", [7496, 4001])
    async def test_live_port_refused_by_default(self, port: int) -> None:
        broker = IBKRBroker(IBKRConfig(port=port))
        assert broker.allow_live is False

        with pytest.raises(RuntimeError, match=str(port)):
            await broker.connect()

        # Refused before ever touching ib_insync.
        assert broker._ib is None

    @pytest.mark.parametrize("port", [7496, 4001])
    async def test_live_port_allowed_when_flag_set(
        self, port: int, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_ib = _FakeConnectIB()
        _install_fake_ib_insync(monkeypatch, fake_ib)

        broker = IBKRBroker(IBKRConfig(port=port), allow_live=True)
        await broker.connect()

        assert fake_ib.connect_kwargs["port"] == port

    @pytest.mark.parametrize("port", [7497, 4002])
    async def test_paper_ports_not_blocked_by_guard(
        self, port: int, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_ib = _FakeConnectIB()
        _install_fake_ib_insync(monkeypatch, fake_ib)

        broker = IBKRBroker(IBKRConfig(port=port), allow_live=False)
        await broker.connect()

        assert fake_ib.connect_kwargs["port"] == port


def _install_fake_ib_insync_for_orders(monkeypatch, fake_ib_instance) -> None:
    """Install a fake `ib_insync` module providing IB/Stock/MarketOrder/
    LimitOrder - enough for IBKRBroker.submit_order()'s local `from
    ib_insync import ...` imports to resolve after a mid-submit reconnect
    (D4), not just connect()'s own import."""
    fake_module = types.ModuleType("ib_insync")
    fake_module.IB = lambda: fake_ib_instance

    class _Stock:
        def __init__(self, symbol, exchange, currency):
            self.symbol = symbol

    class _MarketOrder:
        def __init__(self, action, totalQuantity):
            self.action = action
            self.totalQuantity = totalQuantity

    class _LimitOrder:
        def __init__(self, action, totalQuantity, lmtPrice):
            self.action = action
            self.totalQuantity = totalQuantity
            self.lmtPrice = lmtPrice

    fake_module.Stock = _Stock
    fake_module.MarketOrder = _MarketOrder
    fake_module.LimitOrder = _LimitOrder
    monkeypatch.setitem(sys.modules, "ib_insync", fake_module)


class _FakeReconnectIB:
    """Fake ib_insync.IB exercising IBKRBroker's reconnect-on-submit path
    (D4): starts disconnected, connectAsync() flips it connected,
    placeOrder() records the call and hands back an incrementing orderId."""

    def __init__(self):
        self.connect_kwargs: dict | None = None
        self.orderStatusEvent = MagicMock()
        self.execDetailsEvent = MagicMock()
        self.disconnectedEvent = MagicMock()
        self._connected = False
        self.placed: list = []

    async def connectAsync(self, host, port, clientId):
        self.connect_kwargs = {"host": host, "port": port, "clientId": clientId}
        self._connected = True

    def isConnected(self) -> bool:
        return self._connected

    def placeOrder(self, contract, order):
        self.placed.append((contract, order))

        class _IBOrder:
            orderId = len(self.placed)

        class _Trade:
            order = _IBOrder()

        return _Trade()


class TestIBKRBrokerReconnectOnSubmit:
    """Tests for IBKRBroker.submit_order's reconnect-on-next-submit (D4):
    when the connection has dropped, submit_order attempts a reconnect
    through connect() itself, so D3's live-port guard and D1's clientId
    apply on every reconnect path exactly as they do on the initial connect.
    """

    def _order(self) -> Order:
        return Order(
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("10"),
        )

    async def test_submit_order_reconnects_when_disconnected(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broker = IBKRBroker(IBKRConfig(port=7497, client_id=2))
        # Simulate a broker that connected once, then dropped (disconnectedEvent
        # flips ib_insync's own isConnected() False on the stale IB object).
        stale_ib = _FakeReconnectIB()
        broker._ib = stale_ib

        fresh_ib = _FakeReconnectIB()
        _install_fake_ib_insync_for_orders(monkeypatch, fresh_ib)

        broker_order_id = await broker.submit_order(self._order())

        assert fresh_ib.connect_kwargs == {
            "host": "127.0.0.1",
            "port": 7497,
            "clientId": 2,
        }
        assert len(fresh_ib.placed) == 1
        assert broker._ib is fresh_ib
        assert broker_order_id == "1"

    async def test_submit_order_reconnect_respects_live_port_guard(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        broker = IBKRBroker(IBKRConfig(port=7496, client_id=2), allow_live=False)
        stale_ib = _FakeReconnectIB()
        broker._ib = stale_ib

        fresh_ib = _FakeReconnectIB()
        _install_fake_ib_insync_for_orders(monkeypatch, fresh_ib)

        with pytest.raises(RuntimeError, match="7496"):
            await broker.submit_order(self._order())

        # The guard fires inside connect() before it ever touches the new
        # ib_insync module.
        assert fresh_ib.connect_kwargs is None
        assert len(fresh_ib.placed) == 0

    async def test_submit_order_sets_explicit_day_tif(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Without an explicit TIF, IBKR applies its order preset and emits
        # warning 10349, which ib_insync 0.9.86 misreads as a fatal order
        # error: the trade is locally marked Cancelled while the real order
        # stays live at IBKR (S3 validation finding, 2026-08-14).
        broker = IBKRBroker(IBKRConfig())
        connected_ib = _FakeReconnectIB()
        connected_ib._connected = True
        broker._ib = connected_ib
        _install_fake_ib_insync_for_orders(monkeypatch, connected_ib)

        await broker.submit_order(self._order())
        limit = self._order()
        limit.order_type = OrderType.LIMIT
        limit.limit_price = Decimal("100")
        await broker.submit_order(limit)

        assert all(order.tif == "DAY" for _, order in connected_ib.placed)

    async def test_submit_order_already_connected_does_not_reconnect(self) -> None:
        broker = IBKRBroker(IBKRConfig())
        connected_ib = _FakeReconnectIB()
        connected_ib._connected = True
        broker._ib = connected_ib

        broker_order_id = await broker.submit_order(self._order())

        # No reconnect attempted: connect_kwargs stays unset on the already-
        # connected instance, and the order was placed on it directly.
        assert connected_ib.connect_kwargs is None
        assert len(connected_ib.placed) == 1
        assert broker_order_id == "1"


class TestIBKRBrokerOnDisconnected:
    """Tests for IBKRBroker's disconnectedEvent hook (D4)."""

    async def test_on_disconnected_does_not_raise(self) -> None:
        broker = IBKRBroker(IBKRConfig())
        # Plain sync ib_insync event handler; must be safe to call directly.
        broker._on_disconnected()
