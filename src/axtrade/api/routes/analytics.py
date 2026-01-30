"""Analytics API endpoints."""

from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query

from axtrade.analytics import (
    DrawdownTracker,
    RollingMetrics,
    TradeRecord,
    calculate_portfolio_summary,
    calculate_rolling_metrics,
    calculate_strategy_performance,
    calculate_trade_stats,
    analyze_time_performance,
    returns_from_equity,
)

from ..dependencies import get_order_repo, get_position_repo
from axtrade.oms.repository import OrderRepository, PositionRepository

router = APIRouter()


async def _get_trades_from_fills(order_repo: OrderRepository) -> list[TradeRecord]:
    """Convert fills to trade records for analytics.

    This is a simplified version - in production you'd want
    proper trade tracking with entry/exit pairing.
    """
    # Get recent fills
    fills = await order_repo.get_recent_fills(limit=1000)

    # Group fills by order to create trade records
    # Simplified: treat each fill as a completed trade
    trades = []
    for fill in fills:
        trade = TradeRecord(
            trade_id=fill.id,
            symbol=fill.symbol,
            strategy_id=fill.strategy_id,
            side=fill.side,
            entry_time=fill.filled_at,
            exit_time=fill.filled_at,  # Same for single-fill trades
            entry_price=fill.price,
            exit_price=fill.price,
            quantity=fill.quantity,
            pnl=Decimal("0"),  # Would need P&L tracking
            commission=fill.commission,
        )
        trades.append(trade)

    return trades


@router.get("/analytics/summary")
async def get_analytics_summary(
    order_repo: OrderRepository = Depends(get_order_repo),
    position_repo: PositionRepository = Depends(get_position_repo),
) -> dict:
    """Get overall portfolio analytics summary.

    Returns:
        Portfolio-level analytics including P&L, win rate, Sharpe, etc.
    """
    trades = await _get_trades_from_fills(order_repo)
    summary = calculate_portfolio_summary(trades)

    return {
        "total_pnl": str(summary.total_pnl),
        "total_trades": summary.total_trades,
        "win_rate": summary.overall_win_rate,
        "profit_factor": summary.overall_profit_factor,
        "sharpe_ratio": summary.overall_sharpe,
        "sortino_ratio": summary.overall_sortino,
        "max_drawdown": summary.max_drawdown,
        "best_strategy": summary.best_strategy,
        "worst_strategy": summary.worst_strategy,
        "strategy_count": summary.strategy_count,
        "avg_correlation": summary.avg_correlation,
    }


@router.get("/analytics/rolling")
async def get_rolling_metrics(
    window: int = Query(default=30, ge=5, le=252),
    order_repo: OrderRepository = Depends(get_order_repo),
) -> dict:
    """Get rolling performance metrics.

    Args:
        window: Number of periods for rolling calculation

    Returns:
        Rolling Sharpe, Sortino, volatility, and return
    """
    # Get daily P&L for rolling calculation
    daily_pnl = await order_repo.get_daily_pnl_series(limit=window * 2)

    if not daily_pnl:
        return {
            "sharpe_ratio": None,
            "sortino_ratio": None,
            "volatility": None,
            "annualized_return": None,
            "window_days": window,
            "data_points": 0,
        }

    # Convert to returns (simplified - using P&L directly)
    # In production, you'd want actual % returns based on equity
    returns = [float(pnl) / 100000 for pnl in daily_pnl]  # Assume 100k base

    metrics = calculate_rolling_metrics(
        returns=returns,
        window_days=window,
    )

    return {
        "sharpe_ratio": metrics.sharpe_ratio,
        "sortino_ratio": metrics.sortino_ratio,
        "volatility": metrics.volatility,
        "annualized_return": metrics.annualized_return,
        "window_days": metrics.window_days,
        "data_points": metrics.data_points,
        "calculated_at": metrics.calculated_at.isoformat(),
    }


@router.get("/analytics/drawdown")
async def get_drawdown_info(
    order_repo: OrderRepository = Depends(get_order_repo),
) -> dict:
    """Get current drawdown information.

    Returns:
        Drawdown metrics including current DD, max DD, peak/trough values
    """
    # Get equity curve from daily P&L
    daily_pnl = await order_repo.get_daily_pnl_series(limit=365)

    if not daily_pnl:
        return {
            "current_drawdown_pct": 0.0,
            "max_drawdown_pct": 0.0,
            "in_drawdown": False,
            "drawdown_duration_days": 0,
        }

    # Build equity curve
    tracker = DrawdownTracker()
    equity = Decimal("100000")  # Starting equity

    for i, pnl in enumerate(reversed(daily_pnl)):
        equity += Decimal(str(pnl))
        # Use index as timestamp proxy
        timestamp = datetime.now(timezone.utc)
        tracker.update(equity, timestamp)

    info = tracker.get_info()

    return {
        "current_drawdown_pct": info.current_drawdown_pct,
        "max_drawdown_pct": info.max_drawdown_pct,
        "current_value": str(info.current_value),
        "peak_value": str(info.peak_value),
        "in_drawdown": info.in_drawdown,
        "drawdown_duration_days": info.drawdown_duration_days,
        "avg_drawdown_pct": info.avg_drawdown_pct,
        "avg_recovery_days": info.avg_recovery_days,
    }


@router.get("/analytics/trades")
async def get_trade_statistics(
    order_repo: OrderRepository = Depends(get_order_repo),
) -> dict:
    """Get trade statistics.

    Returns:
        Win rate, profit factor, expectancy, streaks, etc.
    """
    trades = await _get_trades_from_fills(order_repo)
    stats = calculate_trade_stats(trades)

    return {
        "total_trades": stats.total_trades,
        "winning_trades": stats.winning_trades,
        "losing_trades": stats.losing_trades,
        "breakeven_trades": stats.breakeven_trades,
        "win_rate": stats.win_rate,
        "avg_win": str(stats.avg_win),
        "avg_loss": str(stats.avg_loss),
        "avg_trade": str(stats.avg_trade),
        "avg_win_loss_ratio": stats.avg_win_loss_ratio,
        "profit_factor": stats.profit_factor,
        "expectancy": str(stats.expectancy),
        "total_pnl": str(stats.total_pnl),
        "largest_win": str(stats.largest_win),
        "largest_loss": str(stats.largest_loss),
        "avg_trade_duration_hours": stats.avg_trade_duration.total_seconds() / 3600,
        "max_consecutive_wins": stats.max_consecutive_wins,
        "max_consecutive_losses": stats.max_consecutive_losses,
        "current_streak": stats.current_streak,
    }


@router.get("/analytics/trades/time")
async def get_time_analysis(
    order_repo: OrderRepository = Depends(get_order_repo),
) -> dict:
    """Get time-based performance analysis.

    Returns:
        P&L and trade counts by hour, day of week, and month
    """
    trades = await _get_trades_from_fills(order_repo)
    analysis = analyze_time_performance(trades)

    return {
        "hourly_pnl": {str(k): str(v) for k, v in analysis.hourly_pnl.items()},
        "hourly_trades": analysis.hourly_trades,
        "daily_pnl": {k: str(v) for k, v in analysis.daily_pnl.items()},
        "daily_trades": analysis.daily_trades,
        "monthly_pnl": {k: str(v) for k, v in analysis.monthly_pnl.items()},
        "monthly_trades": analysis.monthly_trades,
    }


@router.get("/analytics/strategies")
async def get_strategy_performance(
    order_repo: OrderRepository = Depends(get_order_repo),
) -> list[dict]:
    """Get per-strategy performance metrics.

    Returns:
        List of strategy performance objects
    """
    trades = await _get_trades_from_fills(order_repo)
    perf = calculate_strategy_performance(trades)

    return [
        {
            "strategy_id": p.strategy_id,
            "total_pnl": str(p.total_pnl),
            "trade_count": p.trade_count,
            "win_rate": p.win_rate,
            "avg_trade_pnl": str(p.avg_trade_pnl),
            "profit_factor": p.profit_factor,
            "sharpe_ratio": p.sharpe_ratio,
            "sortino_ratio": p.sortino_ratio,
            "max_drawdown": p.max_drawdown,
            "avg_trade_duration_hours": p.avg_trade_duration_hours,
            "largest_win": str(p.largest_win),
            "largest_loss": str(p.largest_loss),
        }
        for p in perf.values()
    ]
