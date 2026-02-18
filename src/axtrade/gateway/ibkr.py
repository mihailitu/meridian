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
        self._tick_queue: asyncio.Queue[Tick] = asyncio.Queue(maxsize=50_000)
        self._running = False
        self._dropped_ticks: int = 0

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

    async def _qualify_and_subscribe(self, symbol_configs: list[SymbolConfig]) -> None:
        """Batch-qualify contracts and subscribe to market data.

        Args:
            symbol_configs: List of symbol configs to qualify and subscribe
        """
        if not self._ib or not symbol_configs:
            return

        from ib_insync import Stock

        contracts = [
            Stock(sc.symbol, sc.exchange, sc.currency)
            for sc in symbol_configs
        ]

        qualified = await self._ib.qualifyContractsAsync(*contracts)

        for contract, symbol_config in zip(qualified, symbol_configs):
            if contract.conId:
                self._contracts[symbol_config.symbol] = contract
                self._ib.reqMktData(contract)
                logger.info("subscribed", symbol=symbol_config.symbol)
            else:
                logger.warning("failed_to_qualify", symbol=symbol_config.symbol)

        if len(self._contracts) > 100:
            logger.warning(
                "ibkr_streaming_lines_limit",
                active_lines=len(self._contracts),
                msg="IBKR limits concurrent streaming to 100 lines by default. "
                    "Request additional market data subscriptions if needed.",
            )

    async def subscribe(self, symbols: list[SymbolConfig]) -> None:
        """Subscribe to market data.

        Args:
            symbols: List of symbols to subscribe to
        """
        if not self._ib:
            raise RuntimeError("Not connected to IBKR")

        self._symbols = symbols
        await self._qualify_and_subscribe(symbols)
        self._ib.pendingTickersEvent += self._on_pending_tickers

    async def add_symbols(self, symbols: list[SymbolConfig]) -> None:
        """Dynamically subscribe to additional symbols.

        Args:
            symbols: List of symbols to add
        """
        if not self._ib:
            raise RuntimeError("Not connected to IBKR")

        new_symbols = [s for s in symbols if s.symbol not in self._contracts]
        if not new_symbols:
            return

        await self._qualify_and_subscribe(new_symbols)
        self._symbols.extend(new_symbols)
        logger.info("added_symbols", count=len(new_symbols))

    async def remove_symbols(self, symbols: list[str]) -> None:
        """Dynamically unsubscribe from symbols.

        Args:
            symbols: List of symbol names to remove
        """
        if not self._ib:
            return

        for symbol in symbols:
            contract = self._contracts.pop(symbol, None)
            if contract:
                self._ib.cancelMktData(contract)
                logger.info("unsubscribed", symbol=symbol)

        self._symbols = [s for s in self._symbols if s.symbol not in symbols]

    def _on_pending_tickers(self, tickers: list) -> None:
        """Handle incoming ticker updates.

        Args:
            tickers: List of updated tickers
        """
        for ticker in tickers:
            if ticker.last and ticker.last > 0:
                # Use exchange timestamp when available, fall back to local time
                ts = ticker.time if ticker.time else datetime.now(UTC)
                tick = Tick(
                    symbol=ticker.contract.symbol,
                    price=ticker.last,
                    timestamp=ts,
                    bid=ticker.bid if ticker.bid > 0 else None,
                    ask=ticker.ask if ticker.ask > 0 else None,
                    volume=ticker.volume if ticker.volume > 0 else None,
                )
                try:
                    self._tick_queue.put_nowait(tick)
                except asyncio.QueueFull:
                    self._dropped_ticks += 1
                    if self._dropped_ticks % 1000 == 0:
                        logger.warning(
                            "tick_queue_full",
                            dropped_total=self._dropped_ticks,
                            queue_size=self._tick_queue.maxsize,
                        )

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
