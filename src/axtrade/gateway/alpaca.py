"""Alpaca data adapter using alpaca-py SDK."""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Optional

from ..common import AlpacaConfig, SymbolConfig, Tick, get_logger
from .base import DataAdapter

logger = get_logger(__name__)


class AlpacaAdapter(DataAdapter):
    """Alpaca adapter using alpaca-py SDK.

    Provides real-time stock market data via WebSocket streaming.
    Supports IEX (free) and SIP (paid) data feeds.
    """

    def __init__(self, config: AlpacaConfig):
        """Initialize Alpaca adapter.

        Args:
            config: Alpaca configuration
        """
        self.config = config
        self._stream: Optional[object] = None
        self._connected = False
        self._symbols: list[SymbolConfig] = []
        self._tick_queue: asyncio.Queue[Tick] = asyncio.Queue()
        self._running = False

    def _get_credentials(self) -> tuple[str, str]:
        """Get API credentials from config or environment.

        Returns:
            Tuple of (api_key, secret_key)

        Raises:
            ValueError: If credentials are not configured
        """
        api_key = self.config.api_key or os.environ.get("ALPACA_API_KEY", "")
        secret_key = self.config.secret_key or os.environ.get("ALPACA_SECRET_KEY", "")

        if not api_key or not secret_key:
            raise ValueError(
                "Alpaca credentials not configured. "
                "Set ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables "
                "or configure in config file."
            )

        return api_key, secret_key

    async def connect(self) -> None:
        """Connect to Alpaca WebSocket stream."""
        try:
            from alpaca.data.live import StockDataStream

            api_key, secret_key = self._get_credentials()

            self._stream = StockDataStream(
                api_key=api_key,
                secret_key=secret_key,
                feed=self.config.feed,
            )
            self._connected = True
            logger.info(
                "alpaca_stream_created",
                feed=self.config.feed,
                paper=self.config.paper,
            )
        except ImportError:
            logger.error("alpaca_py_not_installed")
            raise ImportError(
                "alpaca-py is not installed. Install with: pip install alpaca-py"
            )
        except Exception as e:
            logger.error("alpaca_connection_failed", error=str(e))
            raise

    async def disconnect(self) -> None:
        """Disconnect from Alpaca WebSocket stream."""
        self._running = False
        if self._stream:
            try:
                self._stream.stop()
            except Exception as e:
                logger.warning("alpaca_disconnect_error", error=str(e))
            self._stream = None
        self._connected = False
        logger.info("disconnected_from_alpaca")

    def _handle_trade(self, trade) -> None:
        """Handle incoming trade updates.

        Args:
            trade: Trade object from Alpaca
        """
        try:
            tick = Tick(
                symbol=trade.symbol,
                price=float(trade.price),
                timestamp=trade.timestamp.replace(tzinfo=UTC)
                if trade.timestamp.tzinfo is None
                else trade.timestamp,
                volume=int(trade.size) if trade.size else None,
            )
            try:
                self._tick_queue.put_nowait(tick)
            except asyncio.QueueFull:
                pass
        except Exception as e:
            logger.error("alpaca_trade_handler_error", error=str(e))

    def _handle_quote(self, quote) -> None:
        """Handle incoming quote updates.

        Args:
            quote: Quote object from Alpaca
        """
        try:
            tick = Tick(
                symbol=quote.symbol,
                price=float(quote.ask_price + quote.bid_price) / 2,
                timestamp=quote.timestamp.replace(tzinfo=UTC)
                if quote.timestamp.tzinfo is None
                else quote.timestamp,
                bid=float(quote.bid_price) if quote.bid_price else None,
                ask=float(quote.ask_price) if quote.ask_price else None,
            )
            try:
                self._tick_queue.put_nowait(tick)
            except asyncio.QueueFull:
                pass
        except Exception as e:
            logger.error("alpaca_quote_handler_error", error=str(e))

    async def subscribe(self, symbols: list[SymbolConfig]) -> None:
        """Subscribe to market data.

        Args:
            symbols: List of symbols to subscribe to
        """
        if not self._stream:
            raise RuntimeError("Not connected to Alpaca")

        self._symbols = symbols
        symbol_list = [s.symbol for s in symbols]

        self._stream.subscribe_trades(self._handle_trade, *symbol_list)
        self._stream.subscribe_quotes(self._handle_quote, *symbol_list)

        logger.info("alpaca_subscribed", symbols=symbol_list)

    async def stream_ticks(self) -> AsyncIterator[Tick]:
        """Stream ticks from Alpaca.

        Yields:
            Tick objects as they arrive from Alpaca
        """
        if not self._stream:
            raise RuntimeError("Not connected to Alpaca")

        self._running = True

        loop = asyncio.get_event_loop()
        stream_task = loop.run_in_executor(None, self._stream.run)

        try:
            while self._running and self._connected:
                try:
                    tick = await asyncio.wait_for(
                        self._tick_queue.get(),
                        timeout=1.0,
                    )
                    yield tick
                except asyncio.TimeoutError:
                    continue
        finally:
            self._running = False
            if self._stream:
                try:
                    self._stream.stop()
                except Exception:
                    pass
            stream_task.cancel()

    @property
    def connected(self) -> bool:
        """Check if connected to Alpaca."""
        return self._connected and self._stream is not None

    @property
    def name(self) -> str:
        """Return adapter name."""
        return "alpaca"
