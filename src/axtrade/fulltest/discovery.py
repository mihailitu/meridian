"""Sim-time-driven discovery runner for backtest."""

from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from axtrade.common import Config, SymbolConfig, get_logger
from axtrade.discovery.providers import SymbolProvider
from axtrade.discovery.service import DiscoveryService

if TYPE_CHECKING:
    from axtrade.gateway.control import GatewayControlPublisher

logger = get_logger("fulltest.discovery")


class BacktestDiscoveryRunner:
    """Runs discovery scans on the simulation clock instead of wall-clock.

    The aggregator reports each completed bar's timestamp; that is the sim
    clock. Scans run once per sim *day* (the universe is seeded with daily
    bars, so intraday re-scans would see identical data), and every scan is
    bounded by ``as_of`` so discovery can never read bars from the future.
    When gateway_control is provided and auto_subscribe is enabled, feeds
    discovered symbols to the gateway for dynamic replay.
    """

    def __init__(
        self,
        config: Config,
        discovery_service: DiscoveryService,
        symbol_provider: SymbolProvider,
        gateway_control: Optional["GatewayControlPublisher"] = None,
    ):
        self._config = config
        self._discovery_service = discovery_service
        self._symbol_provider = symbol_provider
        self._gateway_control = gateway_control
        self._bar_count = 0
        self._scan_count = 0
        self._total_matches = 0
        self._sim_time: Optional[datetime] = None
        self._last_scan_date: Optional[date] = None
        self._subscribed_symbols: set[str] = set()
        self._symbols_fed: list[str] = []

    async def on_bar(self, bar_time: datetime) -> None:
        """Called after each bar is processed by the aggregator.

        Advances the sim clock and triggers a discovery scan when the
        sim date moves forward.
        """
        self._bar_count += 1
        if self._sim_time is None or bar_time > self._sim_time:
            self._sim_time = bar_time

        if self._last_scan_date == self._sim_time.date():
            return
        self._last_scan_date = self._sim_time.date()

        await self._run_scan()

    async def _run_scan(self) -> None:
        """Run a discovery scan bounded at the current sim time."""
        symbols = await self._symbol_provider.get_symbols()
        if not symbols:
            return

        results = await self._discovery_service.scan(
            symbols=symbols,
            interval=self._config.discovery.interval,
            bar_limit=self._config.discovery.bar_limit,
            as_of=self._sim_time,
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

        # Feed discovered symbols to gateway if configured
        if self._gateway_control and self._config.discovery.auto_subscribe:
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

        # Unlike the live runner, symbols that drop out of discovery are NOT
        # removed from the replay: stopping a symbol's bars would leave the
        # strategy unable to fire the exit for any position it still holds.
        # The strategy exits on score decay; the extra replay only costs time.

    @property
    def scan_count(self) -> int:
        return self._scan_count

    @property
    def total_matches(self) -> int:
        return self._total_matches

    @property
    def symbols_fed(self) -> list[str]:
        return list(self._symbols_fed)
