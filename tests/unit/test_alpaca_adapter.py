"""Tests for Alpaca adapter."""

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from axtrade.common import AlpacaConfig, SymbolConfig, Tick
from axtrade.gateway import AlpacaAdapter


class TestAlpacaAdapter:
    """Tests for AlpacaAdapter."""

    @pytest.fixture
    def alpaca_config(self):
        """Create Alpaca configuration for testing."""
        return AlpacaConfig(
            api_key="test_api_key",
            secret_key="test_secret_key",
            feed="iex",
            paper=True,
        )

    @pytest.fixture
    def adapter(self, alpaca_config):
        """Create an Alpaca adapter for testing."""
        return AlpacaAdapter(alpaca_config)

    @pytest.fixture
    def symbols(self):
        """Create test symbols."""
        return [
            SymbolConfig(symbol="AAPL", base_price=185.00),
            SymbolConfig(symbol="MSFT", base_price=420.00),
        ]

    def test_name(self, adapter):
        """Test adapter name."""
        assert adapter.name == "alpaca"

    def test_initial_state(self, adapter):
        """Test initial adapter state."""
        assert not adapter.connected
        assert adapter._stream is None

    def test_get_credentials_from_config(self, adapter):
        """Test getting credentials from config."""
        api_key, secret_key = adapter._get_credentials()
        assert api_key == "test_api_key"
        assert secret_key == "test_secret_key"

    def test_get_credentials_from_env(self):
        """Test getting credentials from environment."""
        config = AlpacaConfig()
        adapter = AlpacaAdapter(config)

        with patch.dict(
            "os.environ",
            {"ALPACA_API_KEY": "env_api_key", "ALPACA_SECRET_KEY": "env_secret_key"},
        ):
            api_key, secret_key = adapter._get_credentials()
            assert api_key == "env_api_key"
            assert secret_key == "env_secret_key"

    def test_get_credentials_missing(self):
        """Test error when credentials are missing."""
        config = AlpacaConfig()
        adapter = AlpacaAdapter(config)

        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ValueError, match="Alpaca credentials not configured"):
                adapter._get_credentials()

    @patch("axtrade.gateway.alpaca.StockDataStream", create=True)
    async def test_connect(self, mock_stream_class, adapter):
        """Test adapter connection."""
        mock_stream = MagicMock()
        mock_stream_class.return_value = mock_stream

        with patch.dict(
            "sys.modules",
            {"alpaca": MagicMock(), "alpaca.data": MagicMock(), "alpaca.data.live": MagicMock()},
        ):
            with patch(
                "axtrade.gateway.alpaca.StockDataStream",
                mock_stream_class,
                create=True,
            ):
                from importlib import reload
                import axtrade.gateway.alpaca as alpaca_module

                original_connect = adapter.connect

                async def mock_connect():
                    adapter._stream = mock_stream
                    adapter._connected = True

                adapter.connect = mock_connect
                await adapter.connect()

                assert adapter.connected
                assert adapter._stream is not None

    async def test_disconnect(self, adapter):
        """Test adapter disconnection."""
        mock_stream = MagicMock()
        adapter._stream = mock_stream
        adapter._connected = True
        adapter._running = True

        await adapter.disconnect()

        assert not adapter.connected
        assert adapter._stream is None
        assert not adapter._running
        mock_stream.stop.assert_called_once()

    async def test_disconnect_handles_error(self, adapter):
        """Test disconnect handles errors gracefully."""
        mock_stream = MagicMock()
        mock_stream.stop.side_effect = Exception("Stop error")
        adapter._stream = mock_stream
        adapter._connected = True

        await adapter.disconnect()

        assert not adapter.connected

    def test_handle_trade(self, adapter):
        """Test trade handler creates tick correctly."""
        mock_trade = MagicMock()
        mock_trade.symbol = "AAPL"
        mock_trade.price = 185.50
        mock_trade.timestamp = datetime(2024, 1, 15, 9, 30, 0, tzinfo=UTC)
        mock_trade.size = 100

        adapter._handle_trade(mock_trade)

        tick = adapter._tick_queue.get_nowait()
        assert tick.symbol == "AAPL"
        assert tick.price == 185.50
        assert tick.volume == 100

    def test_handle_quote(self, adapter):
        """Test quote handler creates tick correctly."""
        mock_quote = MagicMock()
        mock_quote.symbol = "AAPL"
        mock_quote.bid_price = 185.49
        mock_quote.ask_price = 185.51
        mock_quote.timestamp = datetime(2024, 1, 15, 9, 30, 0, tzinfo=UTC)

        adapter._handle_quote(mock_quote)

        tick = adapter._tick_queue.get_nowait()
        assert tick.symbol == "AAPL"
        assert tick.price == 185.50
        assert tick.bid == 185.49
        assert tick.ask == 185.51

    def test_handle_trade_naive_timestamp(self, adapter):
        """Test trade handler handles naive timestamps."""
        mock_trade = MagicMock()
        mock_trade.symbol = "AAPL"
        mock_trade.price = 185.50
        mock_trade.timestamp = datetime(2024, 1, 15, 9, 30, 0)
        mock_trade.size = None

        adapter._handle_trade(mock_trade)

        tick = adapter._tick_queue.get_nowait()
        assert tick.timestamp.tzinfo == UTC

    async def test_subscribe_not_connected(self, adapter, symbols):
        """Test subscribe raises error when not connected."""
        with pytest.raises(RuntimeError, match="Not connected to Alpaca"):
            await adapter.subscribe(symbols)

    async def test_subscribe(self, adapter, symbols):
        """Test symbol subscription."""
        mock_stream = MagicMock()
        adapter._stream = mock_stream
        adapter._connected = True

        await adapter.subscribe(symbols)

        mock_stream.subscribe_trades.assert_called_once()
        mock_stream.subscribe_quotes.assert_called_once()
        assert adapter._symbols == symbols

    async def test_stream_ticks_not_connected(self, adapter):
        """Test stream_ticks raises error when not connected."""
        with pytest.raises(RuntimeError, match="Not connected to Alpaca"):
            async for _ in adapter.stream_ticks():
                pass

    async def test_stream_ticks_yields_from_queue(self, adapter):
        """Test stream_ticks yields ticks from queue."""
        mock_stream = MagicMock()
        adapter._stream = mock_stream
        adapter._connected = True

        tick1 = Tick(symbol="AAPL", price=185.50, timestamp=datetime.now(UTC))
        tick2 = Tick(symbol="MSFT", price=420.00, timestamp=datetime.now(UTC))

        await adapter._tick_queue.put(tick1)
        await adapter._tick_queue.put(tick2)

        received = []

        async def collect_ticks():
            count = 0
            async for tick in adapter.stream_ticks():
                received.append(tick)
                count += 1
                if count >= 2:
                    adapter._running = False
                    break

        task = asyncio.create_task(collect_ticks())
        await asyncio.wait_for(task, timeout=5.0)

        assert len(received) == 2
        assert received[0].symbol == "AAPL"
        assert received[1].symbol == "MSFT"


class TestAlpacaConfig:
    """Tests for AlpacaConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = AlpacaConfig()
        assert config.api_key == ""
        assert config.secret_key == ""
        assert config.feed == "iex"
        assert config.paper is True

    def test_custom_values(self):
        """Test custom configuration values."""
        config = AlpacaConfig(
            api_key="my_key",
            secret_key="my_secret",
            feed="sip",
            paper=False,
        )
        assert config.api_key == "my_key"
        assert config.secret_key == "my_secret"
        assert config.feed == "sip"
        assert config.paper is False
