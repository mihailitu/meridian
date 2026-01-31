"""Yahoo Finance data adapter using yfinance."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Optional

from ..common import SymbolConfig, Tick, YahooConfig, get_logger
from .base import DataAdapter

logger = get_logger(__name__)


class YahooAdapter(DataAdapter):
    """Yahoo Finance adapter using yfinance.

    Provides delayed stock quotes via polling. Yahoo Finance does not
    support real-time streaming, so this adapter polls at configured
    intervals.
    """

    def __init__(self, config: YahooConfig):
        """Initialize Yahoo adapter.

        Args:
            config: Yahoo configuration
        """
        self.config = config
        self._connected = False
        self._symbols: list[SymbolConfig] = []
        self._tickers: Optional[object] = None
        self._running = False

    async def connect(self) -> None:
        """Initialize yfinance connection."""
        try:
            import yfinance  # noqa: F401

            self._connected = True
            logger.info(
                "yahoo_adapter_initialized",
                poll_interval_ms=self.config.poll_interval_ms,
            )
        except ImportError:
            logger.error("yfinance_not_installed")
            raise ImportError(
                "yfinance is not installed. Install with: pip install yfinance"
            )

    async def disconnect(self) -> None:
        """Disconnect from Yahoo Finance."""
        self._running = False
        self._tickers = None
        self._connected = False
        logger.info("disconnected_from_yahoo")

    async def subscribe(self, symbols: list[SymbolConfig]) -> None:
        """Subscribe to market data.

        Args:
            symbols: List of symbols to subscribe to
        """
        if not self._connected:
            raise RuntimeError("Not connected to Yahoo Finance")

        import yfinance as yf

        self._symbols = symbols
        symbol_list = [s.symbol for s in symbols]

        self._tickers = yf.Tickers(" ".join(symbol_list))

        logger.info("yahoo_subscribed", symbols=symbol_list)

    def _fetch_quotes(self) -> list[Tick]:
        """Fetch current quotes for all subscribed symbols.

        Returns:
            List of Tick objects with current quotes
        """
        if not self._tickers:
            return []

        ticks = []
        timestamp = datetime.now(UTC)

        for symbol_config in self._symbols:
            try:
                ticker = self._tickers.tickers.get(symbol_config.symbol)
                if not ticker:
                    continue

                info = ticker.fast_info

                price = getattr(info, "last_price", None)
                if price is None:
                    price = getattr(info, "previous_close", None)

                if price is None or price <= 0:
                    continue

                bid = getattr(info, "bid", None) if hasattr(info, "bid") else None
                ask = getattr(info, "ask", None) if hasattr(info, "ask") else None

                tick = Tick(
                    symbol=symbol_config.symbol,
                    price=float(price),
                    timestamp=timestamp,
                    bid=float(bid) if bid and bid > 0 else None,
                    ask=float(ask) if ask and ask > 0 else None,
                )
                ticks.append(tick)

            except Exception as e:
                logger.warning(
                    "yahoo_quote_fetch_error",
                    symbol=symbol_config.symbol,
                    error=str(e),
                )

        return ticks

    async def stream_ticks(self) -> AsyncIterator[Tick]:
        """Stream ticks from Yahoo Finance via polling.

        Yields:
            Tick objects as they are fetched
        """
        if not self._connected:
            raise RuntimeError("Not connected to Yahoo Finance")

        self._running = True
        poll_interval = self.config.poll_interval_ms / 1000.0

        while self._running and self._connected:
            try:
                loop = asyncio.get_event_loop()
                ticks = await loop.run_in_executor(None, self._fetch_quotes)

                for tick in ticks:
                    yield tick

                await asyncio.sleep(poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("yahoo_stream_error", error=str(e))
                await asyncio.sleep(poll_interval)

    @property
    def connected(self) -> bool:
        """Check if connected to Yahoo Finance."""
        return self._connected

    @property
    def name(self) -> str:
        """Return adapter name."""
        return "yahoo"
