"""Market regime API endpoints."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query

from axtrade.common import BarRepository, DatabasePool

from ..dependencies import state
from ..schemas import (
    RegimeCurrentResponse,
    RegimeHistoryPoint,
    RegimeHistoryResponse,
    RegimeSummaryResponse,
)

router = APIRouter()


def get_bar_repo() -> BarRepository:
    """Get bar repository dependency."""
    if state.db_pool is None:
        raise RuntimeError("Database pool not initialized")
    return BarRepository(state.db_pool)


@router.get("/regime/current", response_model=RegimeCurrentResponse)
async def get_current_regime(
    symbol: str = Query(..., description="Symbol to get regime for"),
    interval: str = Query("1m", description="Bar interval"),
    bar_repo: BarRepository = Depends(get_bar_repo),
) -> RegimeCurrentResponse:
    """Get current market regime for a symbol.

    Returns the latest regime classification based on recent bars.
    """
    # Get recent bars for regime calculation
    bars = await bar_repo.get_recent_bars(symbol, interval, limit=50)

    if not bars:
        return RegimeCurrentResponse(
            symbol=symbol,
            interval=interval,
            regime=None,
            trend=None,
            volatility=None,
            trend_strength=None,
            volatility_percentile=None,
            timestamp=datetime.now(timezone.utc),
        )

    # Extract OHLC data
    closes = [b.close for b in bars]
    highs = [b.high for b in bars]
    lows = [b.low for b in bars]

    # Calculate regime
    from axtrade.indicators import calculate_regime

    result = calculate_regime(
        closes=closes,
        highs=highs,
        lows=lows,
    )

    if not result:
        return RegimeCurrentResponse(
            symbol=symbol,
            interval=interval,
            regime=None,
            trend=None,
            volatility=None,
            trend_strength=None,
            volatility_percentile=None,
            timestamp=bars[-1].timestamp,
        )

    return RegimeCurrentResponse(
        symbol=symbol,
        interval=interval,
        regime=result.regime.value,
        trend=result.trend.value,
        volatility=result.volatility.value,
        trend_strength=result.trend_strength,
        volatility_percentile=result.volatility_percentile,
        timestamp=bars[-1].timestamp,
    )


@router.get("/regime/history", response_model=RegimeHistoryResponse)
async def get_regime_history(
    symbol: str = Query(..., description="Symbol to get history for"),
    interval: str = Query("1m", description="Bar interval"),
    hours: int = Query(24, ge=1, le=168, description="Hours of history"),
    bar_repo: BarRepository = Depends(get_bar_repo),
) -> RegimeHistoryResponse:
    """Get regime history for a symbol over a time period.

    Returns regime classifications calculated at each bar.
    """
    # Get historical bars
    bars = await bar_repo.get_bars_since(
        symbol,
        interval,
        since=datetime.now(timezone.utc) - timedelta(hours=hours),
    )

    if len(bars) < 21:  # Need enough data for regime calculation
        return RegimeHistoryResponse(
            symbol=symbol,
            interval=interval,
            history=[],
        )

    from axtrade.indicators import RegimeEngine

    # Process bars through regime engine
    engine = RegimeEngine()
    history = []

    for bar in bars:
        result = engine.process_bar(
            symbol=symbol,
            interval=interval,
            open_=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
        )

        if result:
            history.append(
                RegimeHistoryPoint(
                    timestamp=bar.timestamp,
                    regime=result.regime.value,
                    trend=result.trend.value,
                    volatility=result.volatility.value,
                    trend_strength=result.trend_strength,
                    volatility_percentile=result.volatility_percentile,
                )
            )

    return RegimeHistoryResponse(
        symbol=symbol,
        interval=interval,
        history=history,
    )


@router.get("/regime/summary", response_model=list[RegimeSummaryResponse])
async def get_regime_summary(
    interval: str = Query("1m", description="Bar interval"),
    bar_repo: BarRepository = Depends(get_bar_repo),
) -> list[RegimeSummaryResponse]:
    """Get current regime summary for all tracked symbols."""
    from axtrade.common import load_config
    from axtrade.indicators import calculate_regime

    config = load_config()
    symbols = [s.symbol for s in config.gateway.symbols]

    results = []
    for symbol in symbols:
        bars = await bar_repo.get_recent_bars(symbol, interval, limit=50)

        if not bars:
            results.append(
                RegimeSummaryResponse(
                    symbol=symbol,
                    regime=None,
                    trend=None,
                    volatility=None,
                    last_price=None,
                    timestamp=None,
                )
            )
            continue

        closes = [b.close for b in bars]
        highs = [b.high for b in bars]
        lows = [b.low for b in bars]

        regime_result = calculate_regime(
            closes=closes,
            highs=highs,
            lows=lows,
        )

        if regime_result:
            results.append(
                RegimeSummaryResponse(
                    symbol=symbol,
                    regime=regime_result.regime.value,
                    trend=regime_result.trend.value,
                    volatility=regime_result.volatility.value,
                    last_price=bars[-1].close,
                    timestamp=bars[-1].timestamp,
                )
            )
        else:
            results.append(
                RegimeSummaryResponse(
                    symbol=symbol,
                    regime=None,
                    trend=None,
                    volatility=None,
                    last_price=bars[-1].close if bars else None,
                    timestamp=bars[-1].timestamp if bars else None,
                )
            )

    return results
