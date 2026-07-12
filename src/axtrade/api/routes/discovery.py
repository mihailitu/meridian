"""Discovery API endpoints.

Discovery scanning runs in the strategy-runner process now (audit P1-3):
trading must not depend on the API process for discovery_momentum to see
fresh scores. The API is a reader (discovered_symbols table via
DiscoveryRepository) plus a command publisher (axtrade:discovery:control,
handled by DiscoveryRunner) -- it no longer holds a live DiscoveryService.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from axtrade.discovery import DiscoveryControlPublisher, DiscoveryRepository, DiscoveryService

from ..auth import require_api_key
from ..dependencies import get_discovery_control, get_discovery_repo
from ..schemas import (
    AddSymbolRequest,
    DiscoveredSymbolResponse,
    DiscoveryCommandAcceptedResponse,
    DiscoveryStateResponse,
    ScreenerSummaryResponse,
)

router = APIRouter()

# Screener definitions are static (the default set DiscoveryService
# registers in _init_default_screeners); reading their name/type/params
# doesn't need a live, connected scanning service, so a throwaway instance
# built once at import time is enough -- avoids depending on the
# cross-process scanner just to describe what it runs.
_SCREENER_REGISTRY = DiscoveryService()


@router.get("/discovery/state", response_model=DiscoveryStateResponse)
async def get_discovery_state(
    discovery_repo: DiscoveryRepository = Depends(get_discovery_repo),
) -> DiscoveryStateResponse:
    """Get current discovery state, read from the database."""
    last_scan = await discovery_repo.last_scan_at()
    total = await discovery_repo.count()
    return DiscoveryStateResponse(
        active_screeners=_SCREENER_REGISTRY.get_screener_names(),
        last_scan=last_scan.isoformat() if last_scan else None,
        total_discovered=total,
        # Not tracked cross-process: the scanner runs in another process and
        # only persists completed scans, so there's no in-flight state to
        # report here. Best-effort false.
        is_scanning=False,
    )


@router.get("/discovery/symbols", response_model=list[DiscoveredSymbolResponse])
async def get_discovered_symbols(
    min_score: Optional[float] = Query(None, description="Minimum absolute score"),
    source: Optional[str] = Query(None, description="Filter by screener source"),
    bullish_only: bool = Query(False, description="Only bullish signals"),
    bearish_only: bool = Query(False, description="Only bearish signals"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    discovery_repo: DiscoveryRepository = Depends(get_discovery_repo),
) -> list[DiscoveredSymbolResponse]:
    """Get discovered symbols with optional filtering."""
    symbols = await discovery_repo.get_discovered(
        min_score=min_score,
        source=source,
        bullish_only=bullish_only,
        bearish_only=bearish_only,
        limit=limit,
    )
    return [
        DiscoveredSymbolResponse(
            symbol=s.symbol,
            source=s.source,
            score=s.score,
            price=s.price,
            volume=s.volume,
            change_pct=s.change_pct,
            discovered_at=s.discovered_at.isoformat(),
            metadata=s.metadata,
        )
        for s in symbols
    ]


@router.post(
    "/discovery/scan",
    response_model=DiscoveryCommandAcceptedResponse,
    status_code=202,
    dependencies=[Depends(require_api_key)],
)
async def run_scan(
    discovery_control: DiscoveryControlPublisher = Depends(get_discovery_control),
) -> DiscoveryCommandAcceptedResponse:
    """Trigger an immediate discovery scan.

    Scanning happens asynchronously in the strategy-runner process; this
    publishes the command and returns immediately. Poll GET /discovery/state
    or /discovery/symbols for results.
    """
    await discovery_control.scan()
    return DiscoveryCommandAcceptedResponse(
        command="scan",
        message="Scan command published",
    )


@router.get("/discovery/screeners", response_model=list[ScreenerSummaryResponse])
async def get_screeners() -> list[ScreenerSummaryResponse]:
    """Get list of available screeners."""
    return [
        ScreenerSummaryResponse(
            name=screener.name,
            type=screener.screener_type.value,
            params=screener.params,
        )
        for screener in _SCREENER_REGISTRY._screeners.values()
    ]


@router.post(
    "/discovery/symbols",
    response_model=DiscoveryCommandAcceptedResponse,
    status_code=202,
    dependencies=[Depends(require_api_key)],
)
async def add_symbol(
    request: AddSymbolRequest,
    discovery_control: DiscoveryControlPublisher = Depends(get_discovery_control),
) -> DiscoveryCommandAcceptedResponse:
    """Add a symbol manually to the watchlist.

    Published as a command; the symbol appears in GET /discovery/symbols
    once the strategy-runner process's DiscoveryRunner has processed it and
    the next scan has persisted the cache (or immediately once picked up by
    the control subscriber's in-memory add -- visible cross-process after
    the next periodic scan).
    """
    if not request.symbol:
        raise HTTPException(status_code=400, detail="symbol is required")

    await discovery_control.add_symbols([
        {"symbol": request.symbol, "price": request.price, "notes": request.notes}
    ])
    return DiscoveryCommandAcceptedResponse(
        command="add_symbols",
        message=f"Add-symbol command published for {request.symbol.upper()}",
    )


@router.delete(
    "/discovery/symbols",
    response_model=DiscoveryCommandAcceptedResponse,
    dependencies=[Depends(require_api_key)],
)
async def clear_discovered(
    discovery_control: DiscoveryControlPublisher = Depends(get_discovery_control),
) -> DiscoveryCommandAcceptedResponse:
    """Clear all discovered symbols."""
    await discovery_control.remove_symbols()
    return DiscoveryCommandAcceptedResponse(
        command="remove_symbols",
        message="Clear command published",
    )
