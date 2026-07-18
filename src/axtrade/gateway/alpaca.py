"""Alpaca data adapter using alpaca-py SDK."""

import asyncio
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Optional

from ..common import AlpacaConfig, SymbolConfig, Tick, get_logger
from .base import DataAdapter

logger = get_logger(__name__)

# Sentinel enqueued to signal that the underlying stream.run() executor task
# has died (raised or returned) so stream_ticks() can raise loudly instead of
# silently draining nothing forever.
_STREAM_DEAD = object()


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
        # The gateway loop that stream_ticks() runs on. StockDataStream.run()
        # hosts its own event loop inside the executor thread, so the async
        # handlers (_handle_trade/_handle_quote) execute there, not here -
        # this lets them hand ticks back thread-safely (see _emit_tick).
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._stream_dead = False
        self._stream_death_error: Optional[str] = None

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
            from alpaca.data.enums import DataFeed

            api_key, secret_key = self._get_credentials()

            feed_map = {
                "iex": DataFeed.IEX,
                "sip": DataFeed.SIP,
            }
            feed = feed_map.get(self.config.feed.lower(), DataFeed.IEX)

            self._stream = StockDataStream(
                api_key=api_key,
                secret_key=secret_key,
                feed=feed,
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

    def _enqueue(self, item) -> None:
        try:
            self._tick_queue.put_nowait(item)
        except asyncio.QueueFull:
            pass

    def _emit_tick(self, tick: Tick) -> None:
        # Handlers run on the stream's own event loop in the executor thread;
        # hand the tick to the gateway loop thread-safely so the getter wakes
        # immediately instead of draining on the 1s timeout poll.
        loop = self._loop
        if loop is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self._enqueue, tick)
        else:
            self._enqueue(tick)

    async def _handle_trade(self, trade) -> None:
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
            self._emit_tick(tick)
        except Exception as e:
            logger.error("alpaca_trade_handler_error", error=str(e))

    async def _handle_quote(self, quote) -> None:
        """Handle incoming quote updates.

        Args:
            quote: Quote object from Alpaca
        """
        try:
            # IEX quotes are frequently one-sided pre/post-market (bid or ask
            # reported as 0/None). Fabricating a mid from a one-sided quote
            # (e.g. bid=0, ask=200 -> 100.00) poisons bar OHLC, so skip the
            # quote entirely rather than emit a bogus tick.
            if not quote.bid_price or not quote.ask_price:
                return
            if float(quote.bid_price) <= 0 or float(quote.ask_price) <= 0:
                return

            tick = Tick(
                symbol=quote.symbol,
                price=float(quote.ask_price + quote.bid_price) / 2,
                timestamp=quote.timestamp.replace(tzinfo=UTC)
                if quote.timestamp.tzinfo is None
                else quote.timestamp,
                bid=float(quote.bid_price),
                ask=float(quote.ask_price),
            )
            self._emit_tick(tick)
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

    async def add_symbols(self, symbols: list[SymbolConfig]) -> None:
        """Dynamically subscribe to additional symbols."""
        if not self._stream:
            raise RuntimeError("Not connected to Alpaca")

        existing = {s.symbol for s in self._symbols}
        new_symbols = [s for s in symbols if s.symbol not in existing]
        if not new_symbols:
            return

        self._symbols.extend(new_symbols)
        new_names = [s.symbol for s in new_symbols]

        self._stream.subscribe_trades(self._handle_trade, *new_names)
        self._stream.subscribe_quotes(self._handle_quote, *new_names)
        logger.info("alpaca_added_symbols", symbols=new_names)

    async def remove_symbols(self, symbols: list[str]) -> None:
        """Dynamically unsubscribe from symbols."""
        if not self._stream:
            return

        remove_set = set(symbols)
        to_remove = [s for s in symbols if any(sc.symbol == s for sc in self._symbols)]
        if not to_remove:
            return

        self._stream.unsubscribe_trades(*to_remove)
        self._stream.unsubscribe_quotes(*to_remove)
        self._symbols = [s for s in self._symbols if s.symbol not in remove_set]
        logger.info("alpaca_removed_symbols", symbols=to_remove)

    def _on_stream_run_done(self, fut) -> None:
        """Done-callback for the stream.run() executor task.

        run_in_executor's future resolves on the gateway loop, so this runs
        there (not the stream's internal loop). Without this callback,
        stream.run() raising (auth/subscription error) or returning
        (websocket death) silently stops all tick flow - the getter just
        keeps timing out with nothing to report.
        """
        if fut.cancelled():
            return
        exc = fut.exception()
        if not self._running:
            return  # normal shutdown
        self._stream_death_error = (
            str(exc) if exc else "stream.run() returned unexpectedly"
        )
        logger.error("alpaca_stream_died", error=self._stream_death_error)
        self._enqueue(_STREAM_DEAD)

    async def stream_ticks(self) -> AsyncIterator[Tick]:
        """Stream ticks from Alpaca.

        Yields:
            Tick objects as they arrive from Alpaca

        Raises:
            RuntimeError: If the underlying stream.run() dies (raises or
                returns). The caller (GatewayService's stream supervisor)
                retries by calling this again, which rebuilds the stream
                below since a prior death was recorded.
        """
        if not self._stream:
            raise RuntimeError("Not connected to Alpaca")

        if self._stream_dead:
            # A previous stream.run() died; the old stream object is stopped
            # for good, so rebuild it before streaming again.
            logger.warning("alpaca_stream_rebuild", last_error=self._stream_death_error)
            await self.disconnect()
            await self.connect()
            if self._symbols:
                await self.subscribe(list(self._symbols))
            self._stream_dead = False
            self._stream_death_error = None
            while not self._tick_queue.empty():
                self._tick_queue.get_nowait()

        self._running = True
        self._loop = asyncio.get_running_loop()

        stream_task = self._loop.run_in_executor(None, self._stream.run)
        stream_task.add_done_callback(self._on_stream_run_done)

        try:
            while self._running and self._connected:
                try:
                    item = await asyncio.wait_for(
                        self._tick_queue.get(),
                        timeout=1.0,
                    )
                    if item is _STREAM_DEAD:
                        self._stream_dead = True
                        raise RuntimeError(
                            f"alpaca stream died: {self._stream_death_error}"
                        )
                    yield item
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
