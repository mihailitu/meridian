"""IBKR data adapter using ib_insync."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Optional

from ..common import IBKRConfig, SymbolConfig, Tick, get_logger
from .base import DataAdapter

logger = get_logger(__name__)


class IBKRAdapter(DataAdapter):
    """IBKR adapter using ib_insync.

    Requires TWS or IB Gateway to be running and accepting connections.
    """

    def __init__(self, config: IBKRConfig):
        """Initialize IBKR adapter.

        Args:
            config: IBKR configuration
        """
        self.config = config
        self._ib: Optional[object] = None
        self._connected = False
        self._symbols: list[SymbolConfig] = []
        self._contracts: dict[str, object] = {}
        self._tick_queue: asyncio.Queue[Tick] = asyncio.Queue()
        self._running = False

    async def connect(self) -> None:
        """Connect to TWS/IB Gateway."""
        try:
            from ib_insync import IB

            self._ib = IB()
            await self._ib.connectAsync(
                host=self.config.host,
                port=self.config.port,
                clientId=self.config.client_id,
            )
            self._connected = True
            logger.info(
                "connected_to_ibkr",
                host=self.config.host,
                port=self.config.port,
            )
        except Exception as e:
            logger.error("ibkr_connection_failed", error=str(e))
            raise

    async def disconnect(self) -> None:
        """Disconnect from TWS/IB Gateway."""
        self._running = False
        if self._ib:
            self._ib.disconnect()
            self._ib = None
        self._connected = False
        logger.info("disconnected_from_ibkr")

    async def subscribe(self, symbols: list[SymbolConfig]) -> None:
        """Subscribe to market data.

        Args:
            symbols: List of symbols to subscribe to
        """
        if not self._ib:
            raise RuntimeError("Not connected to IBKR")

        from ib_insync import Stock

        self._symbols = symbols

        for symbol_config in symbols:
            contract = Stock(
                symbol_config.symbol,
                symbol_config.exchange,
                symbol_config.currency,
            )
            qualified = await self._ib.qualifyContractsAsync(contract)
            if qualified:
                self._contracts[symbol_config.symbol] = qualified[0]
                self._ib.reqMktData(qualified[0])
                logger.info("subscribed", symbol=symbol_config.symbol)
            else:
                logger.warning("failed_to_qualify", symbol=symbol_config.symbol)

        self._ib.pendingTickersEvent += self._on_pending_tickers

    def _on_pending_tickers(self, tickers: list) -> None:
        """Handle incoming ticker updates.

        Args:
            tickers: List of updated tickers
        """
        for ticker in tickers:
            if ticker.last and ticker.last > 0:
                tick = Tick(
                    symbol=ticker.contract.symbol,
                    price=ticker.last,
                    timestamp=datetime.now(UTC),
                    bid=ticker.bid if ticker.bid > 0 else None,
                    ask=ticker.ask if ticker.ask > 0 else None,
                    volume=ticker.volume if ticker.volume > 0 else None,
                )
                try:
                    self._tick_queue.put_nowait(tick)
                except asyncio.QueueFull:
                    pass

    async def stream_ticks(self) -> AsyncIterator[Tick]:
        """Stream ticks from IBKR.

        Yields:
            Tick objects as they arrive from IBKR
        """
        self._running = True

        while self._running and self._connected:
            try:
                tick = await asyncio.wait_for(
                    self._tick_queue.get(),
                    timeout=1.0,
                )
                yield tick
            except asyncio.TimeoutError:
                if self._ib:
                    self._ib.sleep(0)
                continue

    @property
    def connected(self) -> bool:
        """Check if connected to IBKR."""
        return self._connected and self._ib is not None

    @property
    def name(self) -> str:
        """Return adapter name."""
        return "ibkr"
