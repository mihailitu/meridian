"""Tests for gateway control channel and dynamic symbol management."""

import json
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

    async def qualifyContractsAsync(self, contract):
        if self.qualify_succeeds:
            return [contract]
        return []

    def reqMktData(self, contract):
        self.req_mkt_data_calls.append(contract)

    def cancelMktData(self, contract):
        self.cancel_mkt_data_calls.append(contract)


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
