"""Bar-count-driven discovery runner for backtest."""

from typing import Optional

from axtrade.common import Config, get_logger
from axtrade.discovery.providers import SymbolProvider
from axtrade.discovery.service import DiscoveryService

logger = get_logger("fulltest.discovery")


class BacktestDiscoveryRunner:
    """Runs discovery scans based on bar count instead of wall-clock time.

    In a backtest, time moves at replay speed. This runner triggers
    scans every N bars (configurable) instead of every N seconds.
    """

    def __init__(
        self,
        config: Config,
        discovery_service: DiscoveryService,
        symbol_provider: SymbolProvider,
        scan_interval_bars: int = 60,
    ):
        self._config = config
        self._discovery_service = discovery_service
        self._symbol_provider = symbol_provider
        self._scan_interval_bars = scan_interval_bars
        self._bar_count = 0
        self._scan_count = 0
        self._total_matches = 0

    async def on_bar(self) -> None:
        """Called after each bar is processed by the aggregator.

        Triggers a discovery scan every scan_interval_bars bars.
        """
        self._bar_count += 1

        if self._bar_count % self._scan_interval_bars != 0:
            return

        await self._run_scan()

    async def _run_scan(self) -> None:
        """Run a discovery scan."""
        symbols = await self._symbol_provider.get_symbols()
        if not symbols:
            return

        results = await self._discovery_service.scan(
            symbols=symbols,
            interval=self._config.discovery.interval,
            bar_limit=self._config.discovery.bar_limit,
        )

        total_matches = sum(r.match_count for r in results)
        self._total_matches += total_matches
        self._scan_count += 1

        logger.info(
            "Discovery scan complete",
            scan_number=self._scan_count,
            bar_count=self._bar_count,
            symbols_scanned=len(symbols),
            matches=total_matches,
        )

    @property
    def scan_count(self) -> int:
        return self._scan_count

    @property
    def total_matches(self) -> int:
        return self._total_matches
