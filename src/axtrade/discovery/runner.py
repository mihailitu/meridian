"""Background discovery scanner service."""

import asyncio
from typing import TYPE_CHECKING, Optional

from axtrade.alerts import AlertService
from axtrade.alerts.types import AlertCategory
from axtrade.common import Config, LoopSupervisor, SymbolConfig, get_logger

from .control import DiscoveryControlCommand, DiscoveryControlSubscriber
from .providers import SymbolProvider
from .service import DiscoveryService

if TYPE_CHECKING:
    from axtrade.gateway.control import GatewayControlPublisher
    from axtrade.oms.repository import PositionRepository


class DiscoveryRunner:
    """Runs periodic discovery scans in the background.

    Uses LoopSupervisor for resilience with exponential backoff.
    Reads scan_interval_seconds and enabled flag from config. Also listens on
    the discovery control channel (axtrade:discovery:control) for on-demand
    commands published by the API process, which no longer runs its own
    scanner (audit P1-3).
    """

    def __init__(
        self,
        config: Config,
        discovery_service: DiscoveryService,
        symbol_provider: SymbolProvider,
        alert_service: Optional[AlertService] = None,
        gateway_control: Optional["GatewayControlPublisher"] = None,
        position_repo: Optional["PositionRepository"] = None,
    ):
        self._config = config
        self._discovery_service = discovery_service
        self._symbol_provider = symbol_provider
        self._alert_service = alert_service
        self._gateway_control = gateway_control
        self._position_repo = position_repo
        self._logger = get_logger("discovery_runner")
        self._running = False
        self._supervisor: Optional[LoopSupervisor] = None
        self._subscribed_symbols: set[str] = set()
        self._control_subscriber: Optional[DiscoveryControlSubscriber] = None
        self._control_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Start the background scan loop and the control command listener."""
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

        self._control_subscriber = DiscoveryControlSubscriber(
            self._config.redis, self._config.discovery
        )
        await self._control_subscriber.connect()
        self._control_task = asyncio.create_task(self._control_loop())

        self._logger.info(
            "Discovery scanner started",
            interval_seconds=interval,
        )

        await self._scan_loop(interval)

    async def stop(self) -> None:
        """Stop the background scan loop and the control command listener."""
        self._logger.info("Stopping discovery scanner")
        self._running = False
        if self._supervisor:
            self._supervisor.stop()

        if self._control_task:
            self._control_task.cancel()
            try:
                await self._control_task
            except asyncio.CancelledError:
                pass
            self._control_task = None

        if self._control_subscriber:
            await self._control_subscriber.disconnect()
            self._control_subscriber = None

    async def _control_loop(self) -> None:
        """Listen for control commands and apply them."""
        if not self._control_subscriber:
            return

        while self._running:
            try:
                async for command in self._control_subscriber.subscribe():
                    if not self._running:
                        break
                    await self._handle_control_command(command)
                # The subscription generator only ends when the connection is
                # gone or closing; back off before resubscribing so a dead
                # subscription can't busy-spin this loop.
                if self._running:
                    await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error("Error in discovery control loop", error=str(e))
                await asyncio.sleep(1.0)

    async def _handle_control_command(self, command: DiscoveryControlCommand) -> None:
        """Apply a control command published by the API process."""
        if command.command == "scan":
            self._logger.info("Discovery scan triggered via control command")
            try:
                await self._do_scan()
            except Exception as e:
                self._logger.error("Manual scan failed", error=str(e))
        elif command.command == "add_symbols":
            added = False
            for entry in command.symbols:
                symbol = entry.get("symbol")
                if not symbol:
                    continue
                self._discovery_service.add_manual_symbol(
                    symbol=symbol,
                    price=entry.get("price"),
                    notes=entry.get("notes"),
                )
                added = True
            # Persist immediately so the API (which reads the DB) sees the
            # change now rather than after the next periodic scan.
            if added:
                await self._discovery_service.persist_discovered()
        elif command.command == "remove_symbols":
            # DiscoveryService has no per-symbol removal path; this mirrors
            # the pre-existing DELETE /discovery/symbols behavior (clear all).
            self._discovery_service.clear_discovered()
            await self._discovery_service.persist_discovered()
        else:
            self._logger.warning("Unknown discovery control command", command=command.command)

    async def _scan_loop(self, interval: int) -> None:
        """Main scan loop with resilience."""
        if not self._supervisor:
            return

        while self._running:
            try:
                await self._do_scan()
                self._supervisor.reset_errors()
                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                if not await self._supervisor.handle_error(e):
                    break

    async def _do_scan(self) -> None:
        """Run a single discovery scan and its downstream side effects
        (alerts, gateway feed). Shared by the periodic loop and the
        on-demand "scan" control command."""
        symbols = await self._symbol_provider.get_symbols()
        if not symbols:
            self._logger.warning("No symbols available for scanning")
            return

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

        # Feed discovered symbols to gateway
        if self._gateway_control and self._config.discovery.auto_subscribe:
            await self._feed_gateway()

    async def _feed_gateway(self) -> None:
        """Push discovered symbols to gateway for dynamic subscription."""
        if not self._gateway_control:
            return

        min_score = self._config.discovery.min_score
        discovered = self._discovery_service.get_discovered(
            min_score=min_score,
            bullish_only=True,
        )
        discovered_names = {s.symbol for s in discovered}

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
                self._logger.info(
                    "Fed new symbols to gateway",
                    symbols=list(new_symbols),
                )
            except Exception as e:
                self._logger.error("Failed to add symbols to gateway", error=str(e))

        if stale_symbols:
            # An open position (in any strategy) must not be orphaned by
            # unsubscribing its symbol: discovery_momentum's exits only run
            # inside on_bar, so cutting the bar feed would leave the position
            # stuck open forever (audit P1-9).
            held_by: dict[str, list[str]] = {}
            if self._position_repo:
                try:
                    positions = await self._position_repo.get_open_positions()
                    for p in positions:
                        held_by.setdefault(p.symbol, []).append(p.strategy_id)
                except Exception as e:
                    # Fail safe: if we can't tell what's held, keep every
                    # subscription this cycle rather than risk orphaning an
                    # open position. A stale subscription costs little; a
                    # position whose exit logic never sees another bar
                    # stays open forever.
                    self._logger.error(
                        "Failed to check open positions before eviction; "
                        "keeping all subscriptions this cycle",
                        error=str(e),
                    )
                    return

            to_remove = []
            for sym in stale_symbols:
                if sym in held_by:
                    self._logger.info(
                        "symbol stale but held — keeping subscription",
                        symbol=sym,
                        strategies=held_by[sym],
                    )
                    continue
                to_remove.append(sym)

            if to_remove:
                try:
                    await self._gateway_control.remove_symbols(to_remove)
                    self._subscribed_symbols -= set(to_remove)
                    self._logger.info(
                        "Removed stale symbols from gateway",
                        symbols=to_remove,
                    )
                except Exception as e:
                    self._logger.error("Failed to remove symbols from gateway", error=str(e))

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
