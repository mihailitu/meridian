"""Background discovery scanner service."""

import asyncio
from typing import Optional

from axtrade.alerts import AlertService
from axtrade.alerts.types import AlertCategory
from axtrade.common import Config, LoopSupervisor, get_logger

from .providers import SymbolProvider
from .service import DiscoveryService


class DiscoveryRunner:
    """Runs periodic discovery scans in the background.

    Uses LoopSupervisor for resilience with exponential backoff.
    Reads scan_interval_seconds and enabled flag from config.
    """

    def __init__(
        self,
        config: Config,
        discovery_service: DiscoveryService,
        symbol_provider: SymbolProvider,
        alert_service: Optional[AlertService] = None,
    ):
        self._config = config
        self._discovery_service = discovery_service
        self._symbol_provider = symbol_provider
        self._alert_service = alert_service
        self._logger = get_logger("discovery_runner")
        self._running = False
        self._supervisor: Optional[LoopSupervisor] = None

    async def start(self) -> None:
        """Start the background scan loop."""
        if not self._config.discovery.enabled:
            self._logger.info("Discovery scanning disabled in config")
            return

        self._supervisor = LoopSupervisor(
            name="discovery_scan",
            alert_after=3,
            alert_callback=self._on_loop_failure,
        )

        self._running = True
        interval = self._config.discovery.scan_interval_seconds

        self._logger.info(
            "Discovery scanner started",
            interval_seconds=interval,
        )

        await self._scan_loop(interval)

    async def stop(self) -> None:
        """Stop the background scan loop."""
        self._logger.info("Stopping discovery scanner")
        self._running = False
        if self._supervisor:
            self._supervisor.stop()

    async def _scan_loop(self, interval: int) -> None:
        """Main scan loop with resilience."""
        if not self._supervisor:
            return

        while self._running:
            try:
                symbols = await self._symbol_provider.get_symbols()
                if not symbols:
                    self._logger.warning("No symbols available for scanning")
                    await asyncio.sleep(interval)
                    continue

                results = await self._discovery_service.scan(
                    symbols=symbols,
                    interval=self._config.discovery.interval,
                    bar_limit=self._config.discovery.bar_limit,
                )

                total_matches = sum(r.match_count for r in results)
                self._logger.info(
                    "Discovery scan complete",
                    symbols_scanned=len(symbols),
                    screeners_run=len(results),
                    total_matches=total_matches,
                )

                # Alert on high-score discoveries
                if self._alert_service:
                    await self._send_discovery_alerts(results)

                self._supervisor.reset_errors()
                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                if not await self._supervisor.handle_error(e):
                    break

    async def _send_discovery_alerts(self, results: list) -> None:
        """Send alerts for high-score discoveries."""
        if not self._alert_service:
            return

        high_score_symbols = []
        for result in results:
            for symbol in result.symbols:
                if abs(symbol.score) > 70:
                    high_score_symbols.append(
                        f"{symbol.symbol} ({symbol.source}: {symbol.score:.0f})"
                    )

        if high_score_symbols:
            await self._alert_service.info(
                title="Discovery: high-score symbols found",
                message=f"Found {len(high_score_symbols)} symbols: "
                + ", ".join(high_score_symbols[:10]),
                source="discovery_runner",
                category=AlertCategory.TRADING,
                dedupe_key="discovery:high_score",
                dedupe_seconds=self._config.discovery.scan_interval_seconds,
            )

    async def _on_loop_failure(self, loop_name: str, error: Exception) -> None:
        """Alert on repeated scan loop failures."""
        self._logger.critical(
            "Discovery scan loop failure",
            loop=loop_name,
            error=str(error),
            error_type=type(error).__name__,
        )
        if self._alert_service:
            await self._alert_service.error(
                title="Discovery scanner failing",
                message=f"Repeated failures in {loop_name}: {error}",
                source="discovery_runner",
                category=AlertCategory.SYSTEM,
            )
