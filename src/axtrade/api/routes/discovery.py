"""Discovery API endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from axtrade.common import load_config
from axtrade.discovery import DiscoveryService

from ..auth import require_api_key
from ..dependencies import state
from ..schemas import (
    AddSymbolRequest,
    DiscoveredSymbolResponse,
    DiscoveryStateResponse,
    ScreenerResultResponse,
    ScreenerSummaryResponse,
)

router = APIRouter()


def get_discovery_service() -> DiscoveryService:
    """Get discovery service from shared API state."""
    if state.discovery_service is None:
        raise RuntimeError("Discovery service not initialized")
    return state.discovery_service


@router.get("/discovery/state", response_model=DiscoveryStateResponse)
async def get_discovery_state(
    discovery_service: DiscoveryService = Depends(get_discovery_service),
) -> DiscoveryStateResponse:
    """Get current discovery service state."""
    discovery_state = discovery_service.get_state()
    return DiscoveryStateResponse(
        active_screeners=discovery_state.active_screeners,
        last_scan=discovery_state.last_scan.isoformat() if discovery_state.last_scan else None,
        total_discovered=discovery_state.total_discovered,
        is_scanning=discovery_state.is_scanning,
    )


@router.get("/discovery/symbols", response_model=list[DiscoveredSymbolResponse])
async def get_discovered_symbols(
    min_score: Optional[float] = Query(None, description="Minimum absolute score"),
    source: Optional[str] = Query(None, description="Filter by screener source"),
    bullish_only: bool = Query(False, description="Only bullish signals"),
    bearish_only: bool = Query(False, description="Only bearish signals"),
    limit: int = Query(50, ge=1, le=200, description="Maximum results"),
    discovery_service: DiscoveryService = Depends(get_discovery_service),
) -> list[DiscoveredSymbolResponse]:
    """Get discovered symbols with optional filtering."""
    symbols = discovery_service.get_discovered(
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
    response_model=list[ScreenerResultResponse],
    dependencies=[Depends(require_api_key)],
)
async def run_scan(
    screeners: Optional[str] = Query(None, description="Comma-separated screener names"),
    interval: str = Query("1m", description="Bar interval to use"),
    bar_limit: int = Query(50, ge=10, le=200, description="Number of bars to fetch"),
    discovery_service: DiscoveryService = Depends(get_discovery_service),
) -> list[ScreenerResultResponse]:
    """Run screeners on configured symbols.

    Initiates an on-demand scan using the configured screeners.
    """
    config = load_config()
    symbols = [s.symbol for s in config.gateway.symbols]

    if not symbols:
        raise HTTPException(status_code=400, detail="No symbols configured")

    # Parse screener names
    screener_names = None
    if screeners:
        screener_names = [s.strip() for s in screeners.split(",")]

    # Run scan
    results = await discovery_service.scan(
        symbols=symbols,
        screener_names=screener_names,
        interval=interval,
        bar_limit=bar_limit,
    )

    return [
        ScreenerResultResponse(
            screener_name=r.screener_name,
            screener_type=r.screener_type.value,
            match_count=r.match_count,
            total_scanned=r.total_scanned,
            scan_time_ms=r.scan_time_ms,
            timestamp=r.timestamp.isoformat(),
            symbols=[
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
                for s in r.symbols
            ],
        )
        for r in results
    ]


@router.get("/discovery/screeners", response_model=list[ScreenerSummaryResponse])
async def get_screeners(
    discovery_service: DiscoveryService = Depends(get_discovery_service),
) -> list[ScreenerSummaryResponse]:
    """Get list of available screeners."""
    screener_names = discovery_service.get_screener_names()
    # Get the actual screener objects to include type info
    results = []
    for name in screener_names:
        screener = discovery_service._screeners.get(name)
        if screener:
            results.append(
                ScreenerSummaryResponse(
                    name=screener.name,
                    type=screener.screener_type.value,
                    params=screener.params,
                )
            )
    return results


@router.post(
    "/discovery/symbols",
    response_model=DiscoveredSymbolResponse,
    dependencies=[Depends(require_api_key)],
)
async def add_symbol(
    request: AddSymbolRequest,
    discovery_service: DiscoveryService = Depends(get_discovery_service),
) -> DiscoveredSymbolResponse:
    """Add a symbol manually to the watchlist."""
    symbol = discovery_service.add_manual_symbol(
        symbol=request.symbol,
        price=request.price,
        notes=request.notes,
    )
    return DiscoveredSymbolResponse(
        symbol=symbol.symbol,
        source=symbol.source,
        score=symbol.score,
        price=symbol.price,
        volume=symbol.volume,
        change_pct=symbol.change_pct,
        discovered_at=symbol.discovered_at.isoformat(),
        metadata=symbol.metadata,
    )


@router.delete("/discovery/symbols", dependencies=[Depends(require_api_key)])
async def clear_discovered(
    discovery_service: DiscoveryService = Depends(get_discovery_service),
) -> dict:
    """Clear all discovered symbols."""
    discovery_service.clear_discovered()
    return {"status": "ok", "message": "Discovered symbols cleared"}
