"""Markets API endpoints."""

from datetime import timedelta
from typing import Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from axtrade.common import Market, MarketStatus, get_all_market_status, get_market_hours

router = APIRouter()


class MarketStatusResponse(BaseModel):
    """Market status response."""

    market: str
    is_open: bool
    is_extended_hours: bool
    time_until_open: Optional[str]
    time_until_close: Optional[str]
    timezone: str
    local_time: str
    open_time: str
    close_time: str


class AllMarketsStatusResponse(BaseModel):
    """Response for all markets status."""

    markets: list[MarketStatusResponse]


def _format_timedelta(td: Optional[timedelta]) -> Optional[str]:
    """Format timedelta as HH:MM:SS string."""
    if td is None:
        return None
    total_seconds = int(td.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _market_to_response(market: Market) -> MarketStatusResponse:
    """Convert Market to response model."""
    status = MarketStatus.from_market(market)
    hours = get_market_hours(market)

    return MarketStatusResponse(
        market=market.value,
        is_open=status.is_open,
        is_extended_hours=status.is_extended_hours,
        time_until_open=_format_timedelta(status.time_until_open),
        time_until_close=_format_timedelta(status.time_until_close),
        timezone=status.timezone,
        local_time=status.local_time,
        open_time=hours.open_time.strftime("%H:%M"),
        close_time=hours.close_time.strftime("%H:%M"),
    )


@router.get("/markets", response_model=AllMarketsStatusResponse)
async def get_markets_status() -> AllMarketsStatusResponse:
    """Get status of all markets.

    Returns current open/closed status, trading hours, and time until
    next open/close for all supported markets.
    """
    markets = [_market_to_response(market) for market in Market]
    return AllMarketsStatusResponse(markets=markets)


@router.get("/markets/{market_id}", response_model=MarketStatusResponse)
async def get_market_status(market_id: str) -> MarketStatusResponse:
    """Get status of a specific market.

    Args:
        market_id: Market identifier (us, eu, asia, crypto, forex)

    Returns:
        Current status for the specified market
    """
    try:
        market = Market(market_id.lower())
    except ValueError:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=404,
            detail=f"Unknown market: {market_id}. Valid markets: {[m.value for m in Market]}",
        )

    return _market_to_response(market)


@router.get("/markets/open", response_model=list[str])
async def get_open_markets() -> list[str]:
    """Get list of currently open markets."""
    status = get_all_market_status()
    return [market.value for market, is_open in status.items() if is_open]
