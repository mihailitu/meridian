"""Tests for gateway control channel and dynamic symbol management."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from axtrade.common import GatewayConfig, MockConfig, RedisConfig, SymbolConfig
from axtrade.gateway.control import (
    GatewayControlCommand,
    GatewayControlPublisher,
    GatewayControlSubscriber,
)
from axtrade.gateway.mock import MockAdapter


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
        redis_config = RedisConfig(host="localhost", port=8113)
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
