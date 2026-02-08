"""Discovery service for symbol screening."""

import asyncio
from datetime import datetime
from typing import Optional

from axtrade.common import BarRepository, DatabasePool, get_logger

from .screeners import (
    BaseScreener,
    MomentumScreener,
    TrendScreener,
    VolatilityScreener,
    VolumeScreener,
)
from .types import DiscoveredSymbol, DiscoveryState, ScreenerResult


class DiscoveryService:
    """Service for discovering trading opportunities through screening.

    Manages multiple screeners and provides a unified interface for
    scanning symbols and retrieving discoveries.
    """

    def __init__(
        self,
        db_pool: Optional[DatabasePool] = None,
        screeners: Optional[list[BaseScreener]] = None,
    ):
        """Initialize discovery service.

        Args:
            db_pool: Database pool for fetching bar data
            screeners: List of screeners to use (defaults to standard set)
        """
        self.logger = get_logger("discovery")
        self._db_pool = db_pool
        self._bar_repo: Optional[BarRepository] = None

        # Initialize default screeners if none provided
        self._screeners: dict[str, BaseScreener] = {}
        if screeners:
            for screener in screeners:
                self._screeners[screener.name] = screener
        else:
            self._init_default_screeners()

        # State tracking
        self._discovered: dict[str, DiscoveredSymbol] = {}  # symbol -> discovery
        self._last_scan: Optional[datetime] = None
        self._is_scanning = False

    def _init_default_screeners(self) -> None:
        """Initialize the default set of screeners."""
        default_screeners = [
            MomentumScreener(),
            VolatilityScreener(),
            VolumeScreener(),
            TrendScreener(),
        ]
        for screener in default_screeners:
            self._screeners[screener.name] = screener

    async def connect(self) -> None:
        """Initialize database connection."""
        if self._db_pool:
            self._bar_repo = BarRepository(self._db_pool)
            self.logger.info("Discovery service connected to database")

    def add_screener(self, screener: BaseScreener) -> None:
        """Add a screener to the service.

        Args:
            screener: Screener instance to add
        """
        self._screeners[screener.name] = screener
        self.logger.info("Added screener", name=screener.name, type=screener.screener_type.value)

    def remove_screener(self, name: str) -> bool:
        """Remove a screener from the service.

        Args:
            name: Name of screener to remove

        Returns:
            True if removed, False if not found
        """
        if name in self._screeners:
            del self._screeners[name]
            self.logger.info("Removed screener", name=name)
            return True
        return False

    def get_screener_names(self) -> list[str]:
        """Get list of active screener names."""
        return list(self._screeners.keys())

    async def scan(
        self,
        symbols: list[str],
        screener_names: Optional[list[str]] = None,
        interval: str = "1m",
        bar_limit: int = 50,
    ) -> list[ScreenerResult]:
        """Run screeners on a list of symbols.

        Args:
            symbols: List of symbols to scan
            screener_names: Specific screeners to run (None = all)
            interval: Bar interval to use for analysis
            bar_limit: Number of recent bars to fetch

        Returns:
            List of ScreenerResult from each screener
        """
        if self._is_scanning:
            self.logger.warning("Scan already in progress, skipping")
            return []

        self._is_scanning = True
        results = []

        try:
            # Fetch bar data for all symbols
            bars_data = await self._fetch_bars_data(symbols, interval, bar_limit)

            # Determine which screeners to run
            if screener_names:
                screeners_to_run = [
                    self._screeners[name]
                    for name in screener_names
                    if name in self._screeners
                ]
            else:
                screeners_to_run = list(self._screeners.values())

            # Run screeners concurrently
            scan_tasks = [
                screener.scan(symbols, bars_data) for screener in screeners_to_run
            ]
            results = await asyncio.gather(*scan_tasks, return_exceptions=True)

            # Filter out exceptions and process results
            valid_results = []
            for result in results:
                if isinstance(result, Exception):
                    self.logger.error("Screener error", error=str(result))
                elif isinstance(result, ScreenerResult):
                    valid_results.append(result)
                    # Update discovered symbols cache
                    for symbol in result.symbols:
                        self._update_discovered(symbol)

            self._last_scan = datetime.utcnow()
            self.logger.info(
                "Scan complete",
                screeners=len(valid_results),
                symbols=len(symbols),
                discoveries=len(self._discovered),
            )

            return valid_results

        finally:
            self._is_scanning = False

    async def _fetch_bars_data(
        self,
        symbols: list[str],
        interval: str,
        limit: int,
    ) -> dict:
        """Fetch bar data for multiple symbols.

        Args:
            symbols: List of symbols
            interval: Bar interval
            limit: Number of bars to fetch

        Returns:
            Dict mapping symbol -> list of bar dicts
        """
        if not self._bar_repo:
            self.logger.warning("No database connection, returning empty data")
            return {}

        bars_data = {}
        for symbol in symbols:
            try:
                bars = await self._bar_repo.get_bars(symbol, interval, limit)
                # Sort by time ascending (oldest first) for analysis
                bars_data[symbol] = sorted(bars, key=lambda b: b["time"])
            except Exception as e:
                self.logger.debug("Failed to fetch bars", symbol=symbol, error=str(e))

        return bars_data

    def _update_discovered(self, symbol: DiscoveredSymbol) -> None:
        """Update discovered symbols cache.

        Keeps the highest scoring discovery per symbol.
        """
        existing = self._discovered.get(symbol.symbol)
        if existing is None or abs(symbol.score) > abs(existing.score):
            self._discovered[symbol.symbol] = symbol

    def get_discovered(
        self,
        min_score: Optional[float] = None,
        source: Optional[str] = None,
        bullish_only: bool = False,
        bearish_only: bool = False,
        limit: int = 50,
    ) -> list[DiscoveredSymbol]:
        """Get discovered symbols with optional filtering.

        Args:
            min_score: Minimum absolute score threshold
            source: Filter by screener source
            bullish_only: Only return bullish signals
            bearish_only: Only return bearish signals
            limit: Maximum results to return

        Returns:
            List of discovered symbols sorted by absolute score
        """
        results = list(self._discovered.values())

        # Apply filters
        if min_score is not None:
            results = [s for s in results if abs(s.score) >= min_score]

        if source:
            results = [s for s in results if s.source == source]

        if bullish_only:
            results = [s for s in results if s.is_bullish]

        if bearish_only:
            results = [s for s in results if s.is_bearish]

        # Sort by absolute score (strongest signals first)
        results.sort(key=lambda s: abs(s.score), reverse=True)

        return results[:limit]

    def clear_discovered(self) -> None:
        """Clear all discovered symbols."""
        self._discovered.clear()
        self.logger.info("Cleared discovered symbols")

    def add_manual_symbol(
        self,
        symbol: str,
        price: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> DiscoveredSymbol:
        """Add a symbol manually to the discovered list.

        Args:
            symbol: Stock ticker symbol
            price: Optional current price
            notes: Optional notes about the symbol

        Returns:
            The created DiscoveredSymbol
        """
        metadata = {}
        if notes:
            metadata["notes"] = notes

        discovered = DiscoveredSymbol(
            symbol=symbol.upper(),
            source="manual",
            score=0.0,
            price=price,
            metadata=metadata,
        )
        self._discovered[discovered.symbol] = discovered
        self.logger.info(
            "Added manual symbol",
            symbol=discovered.symbol,
            price=price,
        )
        return discovered

    def get_state(self) -> DiscoveryState:
        """Get current discovery service state."""
        return DiscoveryState(
            active_screeners=list(self._screeners.keys()),
            last_scan=self._last_scan,
            total_discovered=len(self._discovered),
            discovered_symbols=list(self._discovered.values()),
            is_scanning=self._is_scanning,
        )
