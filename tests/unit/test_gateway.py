"""Tests for gateway module."""

import pytest

from axtrade.common import MockConfig, SymbolConfig, Tick
from axtrade.gateway import MockAdapter


class TestMockAdapter:
    """Tests for MockAdapter."""

    @pytest.fixture
    def adapter(self, mock_config):
        """Create a mock adapter for testing."""
        return MockAdapter(mock_config)

    @pytest.fixture
    def symbols(self):
        """Create test symbols."""
        return [
            SymbolConfig(symbol="TEST1", base_price=100.00),
            SymbolConfig(symbol="TEST2", base_price=200.00),
        ]

    async def test_connect(self, adapter):
        """Test adapter connection."""
        assert not adapter.connected
        await adapter.connect()
        assert adapter.connected

    async def test_disconnect(self, adapter):
        """Test adapter disconnection."""
        await adapter.connect()
        await adapter.disconnect()
        assert not adapter.connected

    async def test_subscribe(self, adapter, symbols):
        """Test symbol subscription."""
        await adapter.connect()
        await adapter.subscribe(symbols)

        assert adapter.get_price("TEST1") == 100.00
        assert adapter.get_price("TEST2") == 200.00

    async def test_stream_ticks(self, adapter, symbols):
        """Test tick streaming."""
        await adapter.connect()
        await adapter.subscribe(symbols)

        tick_count = 0
        async for tick in adapter.stream_ticks():
            assert isinstance(tick, Tick)
            assert tick.symbol in ["TEST1", "TEST2"]
            assert tick.price > 0
            assert tick.bid is not None
            assert tick.ask is not None
            tick_count += 1
            if tick_count >= 4:
                await adapter.disconnect()
                break

        assert tick_count >= 4

    def test_name(self, adapter):
        """Test adapter name."""
        assert adapter.name == "mock"


class TestTick:
    """Tests for Tick dataclass."""

    def test_to_dict(self):
        """Test tick serialization."""
        from datetime import datetime

        tick = Tick(
            symbol="AAPL",
            price=185.50,
            timestamp=datetime(2024, 1, 15, 9, 30, 0),
            bid=185.49,
            ask=185.51,
            volume=1000,
        )

        data = tick.to_dict()

        assert data["symbol"] == "AAPL"
        assert data["price"] == "185.5"
        assert data["bid"] == "185.49"
        assert data["ask"] == "185.51"
        assert data["volume"] == "1000"
        assert "2024-01-15" in data["timestamp"]

    def test_tick_immutable(self):
        """Test that tick is immutable."""
        tick = Tick(symbol="AAPL", price=185.50)

        with pytest.raises(Exception):
            tick.price = 186.00
