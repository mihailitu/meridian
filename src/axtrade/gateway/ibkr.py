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

    # reqMarketDataType argument: 1 = live streaming, 3 = delayed (15-min).
    # config.market_data_type is validated to one of these keys at load time
    # (IBKRConfig.__post_init__).
    _MARKET_DATA_TYPE = {"live": 1, "delayed": 3}

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
        # ticker.volume is IBKR's cumulative day volume, not a per-tick delta;
        # track the last observed cumulative value per symbol so we can emit
        # a per-tick delta instead of summing day-volume into every bar.
        self._last_cum_volume: dict[str, float] = {}

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

            # A fresh paper account has no paid market-data subscriptions;
            # live streaming data (the ib_insync default) errors with code
            # 354 without one. Default is delayed (D2).
            self._ib.reqMarketDataType(self._MARKET_DATA_TYPE[self.config.market_data_type])
            logger.info(
                "market_data_type_set",
                market_data_type=self.config.market_data_type,
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
        self._last_cum_volume.clear()
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
            self._last_cum_volume.pop(name, None)
            logger.info("unsubscribed", symbol=name)

    def _tick_volume(self, symbol: str, cum_volume: float) -> Optional[int]:
        """Convert IBKR's cumulative day volume into a per-tick delta.

        Args:
            symbol: Ticker symbol
            cum_volume: Current cumulative day volume from the ticker

        Returns:
            The volume delta since the last observation, or None if unknown
            (first observation for the symbol, or a re-baseline after a
            day rollover / reconnect / feed reset caused volume to go down).
        """
        last = self._last_cum_volume.get(symbol)
        if last is None:
            # First observation: we can't attribute the day's prior volume
            # to this single tick.
            self._last_cum_volume[symbol] = cum_volume
            return None

        delta = cum_volume - last
        if delta < 0:
            # Day rollover / reconnect / feed reset - re-baseline.
            self._last_cum_volume[symbol] = cum_volume
            return None

        self._last_cum_volume[symbol] = cum_volume
        return int(delta)

    def _on_pending_tickers(self, tickers: list) -> None:
        """Handle incoming ticker updates.

        Args:
            tickers: List of updated tickers
        """
        for ticker in tickers:
            if ticker.last and ticker.last > 0:
                symbol = ticker.contract.symbol
                # NaN > 0 is False, so NaN volumes are already excluded here.
                if ticker.volume > 0:
                    tick_volume = self._tick_volume(symbol, ticker.volume)
                else:
                    tick_volume = None

                tick = Tick(
                    symbol=symbol,
                    price=ticker.last,
                    timestamp=datetime.now(UTC),
                    bid=ticker.bid if ticker.bid > 0 else None,
                    ask=ticker.ask if ticker.ask > 0 else None,
                    volume=tick_volume,
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
                # ib_insync's event processing already runs on this shared
                # asyncio loop; calling self._ib.sleep(0) here would recurse
                # into loop.run_until_complete() from within the running
                # loop and raise RuntimeError, killing the tick generator.
                continue

    @property
    def connected(self) -> bool:
        """Check if connected to IBKR."""
        return self._connected and self._ib is not None

    @property
    def name(self) -> str:
        """Return adapter name."""
        return "ibkr"
