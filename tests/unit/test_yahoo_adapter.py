"""Tests for Yahoo Finance adapter."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from axtrade.common import SymbolConfig, Tick, YahooConfig
from axtrade.gateway import YahooAdapter


class TestYahooAdapter:
    """Tests for YahooAdapter."""

    @pytest.fixture
    def yahoo_config(self):
        """Create Yahoo configuration for testing."""
        return YahooConfig(poll_interval_ms=1000)

    @pytest.fixture
    def adapter(self, yahoo_config):
        """Create a Yahoo adapter for testing."""
        return YahooAdapter(yahoo_config)

    @pytest.fixture
    def symbols(self):
        """Create test symbols."""
        return [
            SymbolConfig(symbol="AAPL", base_price=185.00),
            SymbolConfig(symbol="MSFT", base_price=420.00),
        ]

    def test_name(self, adapter):
        """Test adapter name."""
        assert adapter.name == "yahoo"

    def test_initial_state(self, adapter):
        """Test initial adapter state."""
        assert not adapter.connected
        assert adapter._tickers is None

    @patch("yfinance.Tickers")
    async def test_connect(self, mock_tickers, adapter):
        """Test adapter connection."""
        with patch.dict("sys.modules", {"yfinance": MagicMock()}):
            await adapter.connect()
            assert adapter.connected

    async def test_disconnect(self, adapter):
        """Test adapter disconnection."""
        adapter._connected = True
        adapter._running = True
        adapter._tickers = MagicMock()

        await adapter.disconnect()

        assert not adapter.connected
        assert adapter._tickers is None
        assert not adapter._running

    async def test_subscribe_not_connected(self, adapter, symbols):
        """Test subscribe raises error when not connected."""
        with pytest.raises(RuntimeError, match="Not connected to Yahoo Finance"):
            await adapter.subscribe(symbols)

    @patch("yfinance.Tickers")
    async def test_subscribe(self, mock_tickers_class, adapter, symbols):
        """Test symbol subscription."""
        adapter._connected = True
        mock_tickers = MagicMock()
        mock_tickers_class.return_value = mock_tickers

        with patch.dict("sys.modules", {"yfinance": MagicMock(Tickers=mock_tickers_class)}):
            import yfinance as yf
            yf.Tickers = mock_tickers_class

            await adapter.subscribe(symbols)

            assert adapter._symbols == symbols
            assert adapter._tickers is not None

    def test_fetch_quotes(self, adapter, symbols):
        """Test fetching quotes."""
        adapter._connected = True
        adapter._symbols = symbols

        mock_ticker_aapl = MagicMock()
        mock_ticker_aapl.fast_info = SimpleNamespace(
            last_price=185.50, bid=185.49, ask=185.51
        )

        mock_ticker_msft = MagicMock()
        mock_ticker_msft.fast_info = SimpleNamespace(
            last_price=420.00, bid=419.99, ask=420.01
        )

        mock_tickers = MagicMock()
        mock_tickers.tickers = {
            "AAPL": mock_ticker_aapl,
            "MSFT": mock_ticker_msft,
        }
        adapter._tickers = mock_tickers

        ticks = adapter._fetch_quotes()

        assert len(ticks) == 2
        assert ticks[0].symbol == "AAPL"
        assert ticks[0].price == 185.50
        assert ticks[1].symbol == "MSFT"
        assert ticks[1].price == 420.00

    def test_fetch_quotes_no_tickers(self, adapter):
        """Test fetch quotes returns empty when no tickers."""
        adapter._tickers = None
        ticks = adapter._fetch_quotes()
        assert ticks == []

    def test_fetch_quotes_handles_missing_symbol(self, adapter, symbols):
        """Test fetch quotes handles missing symbols gracefully."""
        adapter._connected = True
        adapter._symbols = symbols

        mock_tickers = MagicMock()
        mock_tickers.tickers = {}
        adapter._tickers = mock_tickers

        ticks = adapter._fetch_quotes()
        assert ticks == []

    def test_fetch_quotes_handles_invalid_price(self, adapter, symbols):
        """Test fetch quotes skips invalid prices."""
        adapter._connected = True
        adapter._symbols = symbols

        mock_ticker = MagicMock()
        mock_ticker.fast_info = SimpleNamespace(last_price=None, previous_close=None)

        mock_tickers = MagicMock()
        mock_tickers.tickers = {"AAPL": mock_ticker}
        adapter._tickers = mock_tickers

        ticks = adapter._fetch_quotes()
        assert len(ticks) == 0

    def test_fetch_quotes_uses_previous_close(self, adapter, symbols):
        """Test fetch quotes falls back to previous close."""
        adapter._connected = True
        adapter._symbols = [symbols[0]]

        mock_ticker = MagicMock()
        mock_ticker.fast_info = SimpleNamespace(last_price=None, previous_close=184.00)

        mock_tickers = MagicMock()
        mock_tickers.tickers = {"AAPL": mock_ticker}
        adapter._tickers = mock_tickers

        ticks = adapter._fetch_quotes()
        assert len(ticks) == 1
        assert ticks[0].price == 184.00

    async def test_stream_ticks_not_connected(self, adapter):
        """Test stream_ticks raises error when not connected."""
        with pytest.raises(RuntimeError, match="Not connected to Yahoo Finance"):
            async for _ in adapter.stream_ticks():
                pass

    async def test_stream_ticks_yields_from_fetch(self, adapter, symbols):
        """Test stream_ticks yields ticks from fetch."""
        adapter._connected = True
        adapter._symbols = symbols

        tick1 = Tick(symbol="AAPL", price=185.50, timestamp=datetime.now(UTC))
        tick2 = Tick(symbol="MSFT", price=420.00, timestamp=datetime.now(UTC))

        call_count = 0

        def mock_fetch():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [tick1, tick2]
            return []

        adapter._fetch_quotes = mock_fetch

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


class TestYahooConfig:
    """Tests for YahooConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        config = YahooConfig()
        assert config.poll_interval_ms == 5000

    def test_custom_values(self):
        """Test custom configuration values."""
        config = YahooConfig(poll_interval_ms=1000)
        assert config.poll_interval_ms == 1000
