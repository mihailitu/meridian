"""Tests for gateway control channel and dynamic symbol management."""

import asyncio
import json
import sys
import types
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog

from axtrade.common import (
    Config,
    GatewayConfig,
    IBKRConfig,
    MockConfig,
    RedisConfig,
    SymbolConfig,
    Tick,
)
from axtrade.gateway.base import DataAdapter
from axtrade.gateway.control import (
    GatewayControlCommand,
    GatewayControlPublisher,
    GatewayControlSubscriber,
)
from axtrade.gateway.ibkr import IBKRAdapter
from axtrade.gateway.mock import MockAdapter
from axtrade.gateway.service import GatewayService


class TestGatewayControlCommand:
    """Tests for GatewayControlCommand serialization."""

    def test_add_symbols_command(self):
        cmd = GatewayControlCommand(
            action="add_symbols",
            symbols=[{"symbol": "TSLA", "base_price": 250.0}],
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert cmd.action == "add_symbols"
        assert len(cmd.symbols) == 1
        assert cmd.symbols[0]["symbol"] == "TSLA"

    def test_remove_symbols_command(self):
        cmd = GatewayControlCommand(
            action="remove_symbols",
            symbols=[{"symbol": "TSLA"}],
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert cmd.action == "remove_symbols"


class TestGatewayControlPublisher:
    """Tests for GatewayControlPublisher."""

    @pytest.fixture
    def publisher(self):
        redis_config = RedisConfig(host="localhost", port=6379)
        gateway_config = GatewayConfig(control_channel="test:gateway:control")
        return GatewayControlPublisher(redis_config, gateway_config)

    async def test_add_symbols_serialization(self, publisher):
        mock_client = AsyncMock()
        mock_client.publish = AsyncMock(return_value=1)
        publisher._client = mock_client

        symbols = [
            SymbolConfig(symbol="TSLA", base_price=250.0),
            SymbolConfig(symbol="META", base_price=500.0),
        ]
        result = await publisher.add_symbols(symbols)
        assert result == 1

        call_args = mock_client.publish.call_args
        channel = call_args[0][0]
        message = json.loads(call_args[0][1])

        assert channel == "test:gateway:control"
        assert message["action"] == "add_symbols"
        assert len(message["symbols"]) == 2
        assert message["symbols"][0]["symbol"] == "TSLA"
        assert message["symbols"][0]["base_price"] == 250.0

    async def test_remove_symbols_serialization(self, publisher):
        mock_client = AsyncMock()
        mock_client.publish = AsyncMock(return_value=1)
        publisher._client = mock_client

        result = await publisher.remove_symbols(["TSLA", "META"])
        assert result == 1

        call_args = mock_client.publish.call_args
        message = json.loads(call_args[0][1])

        assert message["action"] == "remove_symbols"
        assert len(message["symbols"]) == 2
        assert message["symbols"][0]["symbol"] == "TSLA"

    async def test_publish_not_connected_raises(self, publisher):
        with pytest.raises(RuntimeError, match="Not connected"):
            await publisher.add_symbols([SymbolConfig(symbol="X", base_price=1.0)])


class TestMockAdapterDynamicSymbols:
    """Tests for MockAdapter.add_symbols / remove_symbols."""

    @pytest.fixture
    def adapter(self):
        config = MockConfig(tick_interval_ms=100, volatility=0.001)
        return MockAdapter(config)

    async def test_add_symbols(self, adapter):
        initial = [SymbolConfig(symbol="AAPL", base_price=185.0)]
        await adapter.subscribe(initial)
        assert len(adapter._symbols) == 1

        new = [SymbolConfig(symbol="TSLA", base_price=250.0)]
        await adapter.add_symbols(new)

        assert len(adapter._symbols) == 2
        assert "TSLA" in adapter._prices
        assert adapter._prices["TSLA"] == 250.0

    async def test_add_symbols_deduplicates(self, adapter):
        initial = [SymbolConfig(symbol="AAPL", base_price=185.0)]
        await adapter.subscribe(initial)

        # Adding AAPL again should not duplicate
        await adapter.add_symbols([SymbolConfig(symbol="AAPL", base_price=190.0)])
        assert len(adapter._symbols) == 1
        # Price should remain the original
        assert adapter._prices["AAPL"] == 185.0

    async def test_remove_symbols(self, adapter):
        initial = [
            SymbolConfig(symbol="AAPL", base_price=185.0),
            SymbolConfig(symbol="MSFT", base_price=420.0),
            SymbolConfig(symbol="TSLA", base_price=250.0),
        ]
        await adapter.subscribe(initial)

        await adapter.remove_symbols(["MSFT", "TSLA"])

        assert len(adapter._symbols) == 1
        assert adapter._symbols[0].symbol == "AAPL"
        assert "MSFT" not in adapter._prices
        assert "TSLA" not in adapter._prices

    async def test_remove_nonexistent_symbol(self, adapter):
        initial = [SymbolConfig(symbol="AAPL", base_price=185.0)]
        await adapter.subscribe(initial)

        # Should not raise
        await adapter.remove_symbols(["NOPE"])
        assert len(adapter._symbols) == 1


class _StubAdapter(DataAdapter):
    """Minimal DataAdapter subclass that leaves add_symbols/remove_symbols
    on the base class defaults, to exercise the base-class warning behavior."""

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def subscribe(self, symbols: list[SymbolConfig]) -> None:
        pass

    async def stream_ticks(self) -> AsyncIterator[Tick]:
        return
        yield  # pragma: no cover - makes this an async generator

    @property
    def connected(self) -> bool:
        return False

    @property
    def name(self) -> str:
        return "stub"


class TestDataAdapterDefaultDynamicSymbols:
    """Tests for the DataAdapter base-class add_symbols/remove_symbols defaults."""

    async def test_add_symbols_default_does_not_raise_and_warns(self):
        adapter = _StubAdapter()
        with structlog.testing.capture_logs() as cap_logs:
            await adapter.add_symbols([SymbolConfig(symbol="X", base_price=1.0)])

        events = [entry["event"] for entry in cap_logs]
        assert "dynamic_subscribe_not_supported" in events

    async def test_remove_symbols_default_does_not_raise_and_warns(self):
        adapter = _StubAdapter()
        with structlog.testing.capture_logs() as cap_logs:
            await adapter.remove_symbols(["X"])

        events = [entry["event"] for entry in cap_logs]
        assert "dynamic_unsubscribe_not_supported" in events


class _FakeIB:
    """Minimal fake ib_insync.IB replacement recording market data calls."""

    def __init__(self, qualify_succeeds: bool = True):
        self.qualify_succeeds = qualify_succeeds
        self.req_mkt_data_calls: list = []
        self.cancel_mkt_data_calls: list = []
        self.pendingTickersEvent = MagicMock()
        self.disconnectedEvent = MagicMock()
        self.sleep_calls = 0

    async def qualifyContractsAsync(self, contract):
        if self.qualify_succeeds:
            return [contract]
        return []

    def reqMktData(self, contract):
        self.req_mkt_data_calls.append(contract)

    def cancelMktData(self, contract):
        self.cancel_mkt_data_calls.append(contract)

    def disconnect(self):
        pass

    def sleep(self, secs):
        """ib_insync's IB.sleep(0) raises RuntimeError when called from
        inside a running asyncio loop (audit P0-4 kill (c)); the stream loop
        must never call it."""
        self.sleep_calls += 1
        raise RuntimeError("This event loop is already running")


class _FakeContract:
    def __init__(self, symbol: str):
        self.symbol = symbol


class _FakeTicker:
    """Minimal fake ib_insync.Ticker."""

    def __init__(self, symbol: str, last: float = 100.0, bid: float = 99.9,
                 ask: float = 100.1, volume: float = 0.0):
        self.contract = _FakeContract(symbol)
        self.last = last
        self.bid = bid
        self.ask = ask
        self.volume = volume


class TestIBKRAdapterDynamicSymbols:
    """Tests for IBKRAdapter.add_symbols / remove_symbols."""

    @pytest.fixture
    def adapter(self):
        return IBKRAdapter(IBKRConfig())

    async def test_add_symbols_new_symbol(self, adapter):
        fake = _FakeIB(qualify_succeeds=True)
        adapter._ib = fake
        adapter._connected = True

        await adapter.add_symbols([SymbolConfig(symbol="TSLA", base_price=250.0)])

        assert len(fake.req_mkt_data_calls) == 1
        assert "TSLA" in adapter._contracts
        assert any(s.symbol == "TSLA" for s in adapter._symbols)

    async def test_add_symbols_already_subscribed_is_idempotent(self, adapter):
        fake = _FakeIB(qualify_succeeds=True)
        adapter._ib = fake
        adapter._connected = True
        adapter._contracts["AAPL"] = object()
        adapter._symbols = [SymbolConfig(symbol="AAPL", base_price=185.0)]

        await adapter.add_symbols([SymbolConfig(symbol="AAPL", base_price=190.0)])

        assert len(fake.req_mkt_data_calls) == 0
        assert sum(1 for s in adapter._symbols if s.symbol == "AAPL") == 1

    async def test_add_symbols_qualification_failure(self, adapter):
        fake = _FakeIB(qualify_succeeds=False)
        adapter._ib = fake
        adapter._connected = True

        await adapter.add_symbols([SymbolConfig(symbol="NOPE", base_price=10.0)])

        assert "NOPE" not in adapter._contracts
        assert len(fake.req_mkt_data_calls) == 0

    async def test_add_symbols_not_connected_raises(self, adapter):
        adapter._ib = None

        with pytest.raises(RuntimeError):
            await adapter.add_symbols([SymbolConfig(symbol="TSLA", base_price=250.0)])

    async def test_remove_symbols_not_connected_raises(self, adapter):
        adapter._ib = None

        with pytest.raises(RuntimeError):
            await adapter.remove_symbols(["TSLA"])

    async def test_remove_symbols_subscribed(self, adapter):
        fake = _FakeIB()
        adapter._ib = fake
        adapter._connected = True
        aapl_contract = object()
        msft_contract = object()
        adapter._contracts["AAPL"] = aapl_contract
        adapter._contracts["MSFT"] = msft_contract
        adapter._symbols = [
            SymbolConfig(symbol="AAPL", base_price=185.0),
            SymbolConfig(symbol="MSFT", base_price=420.0),
        ]

        await adapter.remove_symbols(["MSFT"])

        assert fake.cancel_mkt_data_calls == [msft_contract]
        assert "MSFT" not in adapter._contracts
        assert not any(s.symbol == "MSFT" for s in adapter._symbols)
        assert "AAPL" in adapter._contracts

    async def test_remove_symbols_unknown_symbol_is_noop(self, adapter):
        fake = _FakeIB()
        adapter._ib = fake
        adapter._connected = True
        aapl_contract = object()
        adapter._contracts["AAPL"] = aapl_contract
        adapter._symbols = [SymbolConfig(symbol="AAPL", base_price=185.0)]

        await adapter.remove_symbols(["NOPE"])

        assert fake.cancel_mkt_data_calls == []
        assert "AAPL" in adapter._contracts


class _FakeConnectIB:
    """Minimal fake ib_insync.IB for exercising IBKRAdapter.connect() (D2).

    ib_insync can't actually be imported in this environment (eventkit's
    module-level asyncio.get_event_loop() call is incompatible with the
    installed Python), so IBKRAdapter.connect()'s local `from ib_insync
    import IB` is redirected via sys.modules rather than patched directly.
    """

    def __init__(self):
        self.connect_kwargs: dict | None = None
        self.market_data_type_calls: list[int] = []
        self.disconnectedEvent = MagicMock()

    async def connectAsync(self, host, port, clientId):
        self.connect_kwargs = {"host": host, "port": port, "clientId": clientId}

    def reqMarketDataType(self, market_data_type: int) -> None:
        self.market_data_type_calls.append(market_data_type)


def _install_fake_ib_insync(monkeypatch, fake_ib_instance) -> None:
    """Install a fake `ib_insync` module so `from ib_insync import IB` inside
    connect() resolves to a stand-in instead of the real (unimportable)
    package."""
    fake_module = types.ModuleType("ib_insync")
    fake_module.IB = lambda: fake_ib_instance
    monkeypatch.setitem(sys.modules, "ib_insync", fake_module)


class TestIBKRAdapterConnectMarketDataType:
    """Tests for IBKRAdapter.connect() requesting the configured market data
    type (D2): delayed (reqMarketDataType(3)) by default, live (1) when
    gateway.ibkr.market_data_type is set to "live"."""

    async def test_connect_requests_delayed_by_default(self, monkeypatch) -> None:
        fake_ib = _FakeConnectIB()
        _install_fake_ib_insync(monkeypatch, fake_ib)

        adapter = IBKRAdapter(IBKRConfig())
        await adapter.connect()

        assert fake_ib.market_data_type_calls == [3]

    async def test_connect_requests_live_when_configured(self, monkeypatch) -> None:
        fake_ib = _FakeConnectIB()
        _install_fake_ib_insync(monkeypatch, fake_ib)

        adapter = IBKRAdapter(IBKRConfig(market_data_type="live"))
        await adapter.connect()

        assert fake_ib.market_data_type_calls == [1]


class TestGatewayServiceControlCommandReachesIBKRAdapter:
    """Bridge test: control command -> GatewayService -> IBKRAdapter market data request."""

    async def test_control_command_add_symbols_reaches_ibkr_adapter(self):
        ibkr_adapter = IBKRAdapter(IBKRConfig())
        fake = _FakeIB(qualify_succeeds=True)
        ibkr_adapter._ib = fake
        ibkr_adapter._connected = True

        service = GatewayService(Config(), adapter=ibkr_adapter)
        service._adapter = ibkr_adapter

        command = GatewayControlCommand(
            action="add_symbols",
            symbols=[{"symbol": "TSLA", "base_price": 250.0}],
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )

        await service._handle_control_command(command)

        assert len(fake.req_mkt_data_calls) == 1
        assert "TSLA" in ibkr_adapter._contracts


class TestIBKRAdapterVolumeDelta:
    """Tests for IBKRAdapter's cumulative-day-volume-to-delta conversion
    (audit P0-4 kill (b))."""

    @pytest.fixture
    def adapter(self):
        return IBKRAdapter(IBKRConfig())

    def test_delta_sequence(self, adapter):
        """cumulative volumes [1000, 1500, 1500, 1200] for one symbol must
        emit tick volumes [None, 500, 0, None] (last value re-baselines
        after the day-rollover-style drop)."""
        emitted = [adapter._tick_volume("AAPL", v) for v in [1000, 1500, 1500, 1200]]

        assert emitted == [None, 500, 0, None]
        # re-baselined to the post-rollover value
        assert adapter._last_cum_volume["AAPL"] == 1200

    def test_second_symbol_baseline_is_independent(self, adapter):
        assert adapter._tick_volume("AAPL", 1000) is None
        assert adapter._tick_volume("AAPL", 1500) == 500

        # MSFT's first observation must also be None, unaffected by AAPL's
        # already-established baseline.
        assert adapter._tick_volume("MSFT", 5000) is None
        assert adapter._tick_volume("MSFT", 5100) == 100

    def test_on_pending_tickers_emits_delta_volume(self, adapter):
        adapter._ib = _FakeIB()
        adapter._connected = True

        adapter._on_pending_tickers([_FakeTicker("AAPL", last=100.0, volume=1000.0)])
        first = adapter._tick_queue.get_nowait()
        assert first.volume is None

        adapter._on_pending_tickers([_FakeTicker("AAPL", last=100.5, volume=1500.0)])
        second = adapter._tick_queue.get_nowait()
        assert second.volume == 500
        assert isinstance(second.volume, int)

    def test_on_pending_tickers_zero_volume_is_not_usable(self, adapter):
        adapter._ib = _FakeIB()
        adapter._connected = True

        adapter._on_pending_tickers([_FakeTicker("AAPL", last=100.0, volume=0.0)])
        tick = adapter._tick_queue.get_nowait()
        assert tick.volume is None
        assert "AAPL" not in adapter._last_cum_volume

    async def test_disconnect_clears_volume_baseline(self, adapter):
        fake = _FakeIB()
        adapter._ib = fake
        adapter._connected = True
        adapter._last_cum_volume["AAPL"] = 1000

        await adapter.disconnect()

        assert adapter._last_cum_volume == {}

    async def test_remove_symbols_clears_volume_baseline(self, adapter):
        fake = _FakeIB()
        adapter._ib = fake
        adapter._connected = True
        adapter._contracts["AAPL"] = object()
        adapter._symbols = [SymbolConfig(symbol="AAPL", base_price=185.0)]
        adapter._last_cum_volume["AAPL"] = 1000

        await adapter.remove_symbols(["AAPL"])

        assert "AAPL" not in adapter._last_cum_volume


class TestIBKRAdapterStreamLoop:
    """Tests for IBKRAdapter.stream_ticks (audit P0-4 kill (c))."""

    @pytest.fixture
    def adapter(self):
        return IBKRAdapter(IBKRConfig())

    async def test_stream_ticks_idle_timeout_does_not_call_sleep_or_raise(
        self, adapter
    ):
        """With an empty tick queue, the idle-timeout branch must not call
        ib.sleep(0) (which raises RuntimeError inside a running loop) and
        must not propagate any exception out of the generator.

        asyncio.wait_for is mocked to raise TimeoutError immediately so the
        test doesn't burn real wall-clock time waiting out the 1s timeout.
        """
        fake = _FakeIB()
        adapter._ib = fake
        adapter._connected = True

        call_count = 0

        async def fake_wait_for(coro, timeout):
            nonlocal call_count
            call_count += 1
            coro.close()  # never actually awaited; avoid an "unawaited coroutine" warning
            if call_count >= 2:
                adapter._running = False
            raise asyncio.TimeoutError()

        with patch(
            "axtrade.gateway.ibkr.asyncio.wait_for", side_effect=fake_wait_for
        ):
            ticks = [tick async for tick in adapter.stream_ticks()]

        assert ticks == []
        assert call_count == 2
        assert fake.sleep_calls == 0


class _FakeReconnectIB:
    """Fake ib_insync.IB for exercising IBKRAdapter's rebuild-on-redial path
    (D4): supports connect()/disconnect() but not qualifyContractsAsync, so
    tests using it keep adapter._symbols empty (resubscribe is a no-op)."""

    def __init__(self):
        self.connect_kwargs: dict | None = None
        self.market_data_type_calls: list[int] = []
        self.disconnect_calls = 0
        self.pendingTickersEvent = MagicMock()
        self.disconnectedEvent = MagicMock()

    async def connectAsync(self, host, port, clientId):
        self.connect_kwargs = {"host": host, "port": port, "clientId": clientId}

    def reqMarketDataType(self, market_data_type: int) -> None:
        self.market_data_type_calls.append(market_data_type)

    def disconnect(self) -> None:
        self.disconnect_calls += 1


class TestIBKRAdapterDisconnectedEvent:
    """Tests for IBKRAdapter's disconnectedEvent hook (D4): an unexpected
    TWS/Gateway-side disconnect must end stream_ticks() (not spin on an
    empty queue forever) so the gateway's LoopSupervisor reconnects with
    backoff, and the next stream_ticks() call must rebuild the connection."""

    @pytest.fixture
    def adapter(self):
        return IBKRAdapter(IBKRConfig())

    async def test_on_disconnected_marks_disconnected_while_running(self, adapter):
        adapter._running = True
        adapter._connected = True

        adapter._on_disconnected()

        assert adapter._connected is False
        assert adapter._disconnected_unexpectedly is True

    async def test_on_disconnected_during_our_own_shutdown_is_not_unexpected(
        self, adapter
    ):
        """Our own disconnect() sets _running False before calling
        ib.disconnect() (which fires this same event) - that path must not
        be flagged as an unexpected disconnect."""
        adapter._running = False
        adapter._connected = True

        adapter._on_disconnected()

        assert adapter._connected is False
        assert adapter._disconnected_unexpectedly is False

    async def test_disconnected_event_ends_stream_ticks_with_raise(self, adapter):
        """stream_ticks() must raise (not silently return) so the gateway's
        LoopSupervisor.handle_error backoff path actually fires - a plain
        return would busy-spin (empty generator, no backoff) on the next
        immediate retry."""
        fake = _FakeIB()
        adapter._ib = fake
        adapter._connected = True
        adapter._running = True

        call_count = 0

        async def fake_wait_for(coro, timeout):
            nonlocal call_count
            call_count += 1
            coro.close()
            if call_count == 1:
                adapter._on_disconnected()  # simulate a TWS-side disconnect
            raise asyncio.TimeoutError()

        with patch(
            "axtrade.gateway.ibkr.asyncio.wait_for", side_effect=fake_wait_for
        ):
            with pytest.raises(RuntimeError, match="ibkr"):
                _ = [tick async for tick in adapter.stream_ticks()]

        assert adapter._connected is False
        assert adapter._disconnected_unexpectedly is True

    async def test_stream_ticks_rebuilds_connection_after_disconnect(
        self, adapter, monkeypatch
    ):
        """The call after a raise must rebuild the connection (disconnect/
        connect/resubscribe) before streaming again, mirroring the Alpaca
        stream-death rebuild (P2-10)."""
        old_fake = _FakeReconnectIB()
        adapter._ib = old_fake
        adapter._connected = False  # already flipped by the prior disconnectedEvent
        adapter._running = True
        adapter._disconnected_unexpectedly = True
        adapter._symbols = []  # keep resubscribe a no-op; qualify isn't faked here

        new_fake = _FakeReconnectIB()
        _install_fake_ib_insync(monkeypatch, new_fake)

        call_count = 0

        async def fake_wait_for(coro, timeout):
            nonlocal call_count
            call_count += 1
            coro.close()
            adapter._running = False
            raise asyncio.TimeoutError()

        with patch(
            "axtrade.gateway.ibkr.asyncio.wait_for", side_effect=fake_wait_for
        ):
            ticks = [tick async for tick in adapter.stream_ticks()]

        assert ticks == []
        assert old_fake.disconnect_calls == 1
        assert adapter._ib is new_fake
        assert new_fake.connect_kwargs is not None
        assert adapter._disconnected_unexpectedly is False
        assert adapter._connected is True


class TestIBKRAdapterSubscriptionCap:
    """Tests for IBKRAdapter.add_symbols respecting gateway.ibkr.max_subscriptions (D5)."""

    async def test_add_symbols_skips_past_cap(self):
        adapter = IBKRAdapter(IBKRConfig(max_subscriptions=2))
        fake = _FakeIB(qualify_succeeds=True)
        adapter._ib = fake
        adapter._connected = True
        adapter._contracts = {"AAPL": object(), "MSFT": object()}  # already at cap

        with structlog.testing.capture_logs() as cap_logs:
            await adapter.add_symbols([SymbolConfig(symbol="TSLA", base_price=250.0)])

        assert "TSLA" not in adapter._contracts
        assert len(fake.req_mkt_data_calls) == 0
        events = [entry["event"] for entry in cap_logs]
        assert "max_subscriptions_reached" in events

    async def test_add_symbols_stops_mid_batch_at_cap(self):
        adapter = IBKRAdapter(IBKRConfig(max_subscriptions=1))
        fake = _FakeIB(qualify_succeeds=True)
        adapter._ib = fake
        adapter._connected = True

        await adapter.add_symbols(
            [
                SymbolConfig(symbol="AAPL", base_price=185.0),
                SymbolConfig(symbol="MSFT", base_price=420.0),
            ]
        )

        assert "AAPL" in adapter._contracts
        assert "MSFT" not in adapter._contracts
        assert len(fake.req_mkt_data_calls) == 1

    async def test_add_symbols_under_cap_unaffected(self):
        adapter = IBKRAdapter(IBKRConfig(max_subscriptions=90))
        fake = _FakeIB(qualify_succeeds=True)
        adapter._ib = fake
        adapter._connected = True

        await adapter.add_symbols([SymbolConfig(symbol="TSLA", base_price=250.0)])

        assert "TSLA" in adapter._contracts
        assert len(fake.req_mkt_data_calls) == 1
