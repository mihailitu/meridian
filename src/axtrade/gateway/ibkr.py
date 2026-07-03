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

    async def _subscribe_symbol(self, symbol_config: SymbolConfig) -> bool:
        """Qualify a contract and request market data for a single symbol.

        Args:
            symbol_config: Symbol to subscribe to

        Returns:
            True if the contract was qualified and market data requested, False otherwise
        """
        from ib_insync import Stock

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
            return True
        else:
            logger.warning("failed_to_qualify", symbol=symbol_config.symbol)
            return False

    async def subscribe(self, symbols: list[SymbolConfig]) -> None:
        """Subscribe to market data.

        Args:
            symbols: List of symbols to subscribe to
        """
        if not self._ib:
            raise RuntimeError("Not connected to IBKR")

        self._symbols = symbols

        for symbol_config in symbols:
            await self._subscribe_symbol(symbol_config)

        self._ib.pendingTickersEvent += self._on_pending_tickers

    async def add_symbols(self, symbols: list[SymbolConfig]) -> None:
        """Dynamically subscribe to additional symbols.

        Args:
            symbols: List of symbols to add
        """
        if not self._ib:
            raise RuntimeError("Not connected to IBKR")

        for symbol_config in symbols:
            if symbol_config.symbol in self._contracts:
                logger.info("symbol_already_subscribed", symbol=symbol_config.symbol)
                continue
            added = await self._subscribe_symbol(symbol_config)
            if added:
                self._symbols.append(symbol_config)

        logger.info(
            "symbols_added",
            symbols=[s.symbol for s in symbols if s.symbol in self._contracts],
        )

    async def remove_symbols(self, symbols: list[str]) -> None:
        """Dynamically unsubscribe from symbols.

        Args:
            symbols: List of symbol names to remove
        """
        if not self._ib:
            raise RuntimeError("Not connected to IBKR")

        for name in symbols:
            contract = self._contracts.get(name)
            if contract is None:
                logger.info("symbol_not_subscribed", symbol=name)
                continue
            self._ib.cancelMktData(contract)
            del self._contracts[name]
            self._symbols = [s for s in self._symbols if s.symbol != name]
            logger.info("unsubscribed", symbol=name)

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
