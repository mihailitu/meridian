"""Bar-count-driven discovery runner for backtest."""

from collections.abc import Callable
from typing import TYPE_CHECKING, Optional

from axtrade.common import Config, SymbolConfig, get_logger
from axtrade.discovery.providers import SymbolProvider
from axtrade.discovery.service import DiscoveryService

if TYPE_CHECKING:
    from axtrade.gateway.control import GatewayControlPublisher

logger = get_logger("fulltest.discovery")


class BacktestDiscoveryRunner:
    """Runs discovery scans based on bar count instead of wall-clock time.

    In a backtest, time moves at replay speed. This runner triggers
    scans every N bars (configurable) instead of every N seconds.
    When gateway_control is provided and auto_subscribe is enabled,
    feeds discovered symbols to the gateway for dynamic replay.
    When add_symbols_callback is provided, uses it instead of
    gateway_control for direct pipeline symbol injection.
    """

    def __init__(
        self,
        config: Config,
        discovery_service: DiscoveryService,
        symbol_provider: SymbolProvider,
        scan_interval_bars: int = 60,
        gateway_control: Optional["GatewayControlPublisher"] = None,
        add_symbols_callback: Optional[Callable[[list[str]], None]] = None,
    ):
        self._config = config
        self._discovery_service = discovery_service
        self._symbol_provider = symbol_provider
        self._scan_interval_bars = scan_interval_bars
        self._gateway_control = gateway_control
        self._add_symbols_callback = add_symbols_callback
        self._bar_count = 0
        self._scan_count = 0
        self._total_matches = 0
        self._subscribed_symbols: set[str] = set()
        self._symbols_fed: list[str] = []

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

        # Feed discovered symbols via callback (direct pipeline) or gateway
        if self._config.discovery.auto_subscribe:
            if self._add_symbols_callback:
                self._feed_via_callback()
            elif self._gateway_control:
                await self._feed_gateway()

    async def _feed_gateway(self) -> None:
        """Push discovered symbols to gateway for dynamic subscription."""
        if not self._gateway_control:
            return

        min_score = self._config.discovery.min_score
        discovered = self._discovery_service.get_discovered(
            min_score=min_score,
            bullish_only=False,
        )
        discovered_names = {s.symbol for s in discovered}

        logger.debug(
            "Discovery feed check",
            min_score=min_score,
            total_discovered=len(discovered),
            symbols=sorted(discovered_names) if discovered_names else [],
        )

        # Static symbols from gateway config should never be removed
        static_symbols = {s.symbol for s in self._config.gateway.symbols}

        # New symbols to add (discovered but not yet subscribed, not static)
        new_symbols = discovered_names - self._subscribed_symbols - static_symbols
        # Stale symbols to remove (previously subscribed but no longer discovered, not static)
        stale_symbols = self._subscribed_symbols - discovered_names - static_symbols

        if new_symbols:
            configs = [
                SymbolConfig(symbol=sym, base_price=100.0)
                for sym in new_symbols
            ]
            try:
                await self._gateway_control.add_symbols(configs)
                self._subscribed_symbols |= new_symbols
                self._symbols_fed.extend(new_symbols)
                logger.info(
                    "Fed discovered symbols to gateway",
                    symbols=sorted(new_symbols),
                    total_fed=len(self._symbols_fed),
                )
            except Exception as e:
                logger.error("Failed to add symbols to gateway", error=str(e))

        if not new_symbols and not discovered_names:
            logger.debug("No symbols passed discovery filter")

        if stale_symbols:
            try:
                await self._gateway_control.remove_symbols(list(stale_symbols))
                self._subscribed_symbols -= stale_symbols
                logger.info(
                    "Removed stale symbols from gateway",
                    symbols=sorted(stale_symbols),
                )
            except Exception as e:
                logger.error("Failed to remove symbols from gateway", error=str(e))

    def _feed_via_callback(self) -> None:
        """Push discovered symbols via the direct pipeline callback."""
        if not self._add_symbols_callback:
            return

        min_score = self._config.discovery.min_score
        discovered = self._discovery_service.get_discovered(
            min_score=min_score,
            bullish_only=False,
        )
        discovered_names = {s.symbol for s in discovered}

        static_symbols = {s.symbol for s in self._config.gateway.symbols}
        new_symbols = discovered_names - self._subscribed_symbols - static_symbols

        if new_symbols:
            self._add_symbols_callback(sorted(new_symbols))
            self._subscribed_symbols |= new_symbols
            self._symbols_fed.extend(new_symbols)
            logger.info(
                "Fed discovered symbols via callback",
                symbols=sorted(new_symbols),
                total_fed=len(self._symbols_fed),
            )

    @property
    def scan_count(self) -> int:
        return self._scan_count

    @property
    def total_matches(self) -> int:
        return self._total_matches

    @property
    def symbols_fed(self) -> list[str]:
        return list(self._symbols_fed)
