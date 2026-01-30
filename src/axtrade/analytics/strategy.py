"""Strategy-level analytics and correlation."""

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal

from .drawdown import calculate_max_drawdown
from .metrics import calculate_sharpe_ratio, calculate_sortino_ratio
from .trades import TradeRecord, calculate_trade_stats


@dataclass
class StrategyPerformance:
    """Performance metrics for a single strategy."""

    strategy_id: str
    total_pnl: Decimal
    trade_count: int
    win_rate: float  # As percentage
    avg_trade_pnl: Decimal
    profit_factor: float
    sharpe_ratio: float | None
    sortino_ratio: float | None
    max_drawdown: float  # As percentage
    avg_trade_duration_hours: float
    largest_win: Decimal
    largest_loss: Decimal


def calculate_strategy_performance(
    trades: list[TradeRecord],
    strategy_equity: dict[str, list[Decimal]] | None = None,
) -> dict[str, StrategyPerformance]:
    """Calculate performance metrics for each strategy.

    Args:
        trades: List of all trades
        strategy_equity: Optional dict of strategy_id -> equity curve
                        Used for Sharpe/drawdown if provided

    Returns:
        Dictionary mapping strategy_id to StrategyPerformance
    """
    # Group trades by strategy
    by_strategy: dict[str, list[TradeRecord]] = defaultdict(list)
    for trade in trades:
        by_strategy[trade.strategy_id].append(trade)

    results = {}

    for strategy_id, strategy_trades in by_strategy.items():
        stats = calculate_trade_stats(strategy_trades)

        # Calculate returns for ratios
        returns = [float(t.return_pct / 100) for t in strategy_trades]

        # Get equity curve if available
        equity = strategy_equity.get(strategy_id) if strategy_equity else None

        # Calculate drawdown
        max_dd = 0.0
        if equity and len(equity) > 1:
            max_dd = calculate_max_drawdown(equity)

        # Calculate risk metrics
        sharpe = calculate_sharpe_ratio(returns) if len(returns) >= 2 else None
        sortino = calculate_sortino_ratio(returns) if len(returns) >= 2 else None

        # Average duration in hours
        avg_hours = stats.avg_trade_duration.total_seconds() / 3600

        results[strategy_id] = StrategyPerformance(
            strategy_id=strategy_id,
            total_pnl=stats.total_pnl,
            trade_count=stats.total_trades,
            win_rate=stats.win_rate,
            avg_trade_pnl=stats.avg_trade,
            profit_factor=stats.profit_factor,
            sharpe_ratio=sharpe,
            sortino_ratio=sortino,
            max_drawdown=max_dd,
            avg_trade_duration_hours=avg_hours,
            largest_win=stats.largest_win,
            largest_loss=stats.largest_loss,
        )

    return results


def calculate_strategy_returns(
    trades: list[TradeRecord],
    period: str = "daily",
) -> dict[str, list[float]]:
    """Calculate periodic returns for each strategy.

    Groups trades into periods and calculates return for each.

    Args:
        trades: List of trades
        period: "daily", "weekly", or "monthly"

    Returns:
        Dictionary mapping strategy_id to list of period returns
    """
    from collections import defaultdict

    # Group trades by strategy and period
    by_strategy_period: dict[str, dict[str, Decimal]] = defaultdict(
        lambda: defaultdict(Decimal)
    )

    for trade in trades:
        if period == "daily":
            period_key = trade.exit_time.strftime("%Y-%m-%d")
        elif period == "weekly":
            # Get ISO week
            period_key = trade.exit_time.strftime("%Y-W%W")
        else:  # monthly
            period_key = trade.exit_time.strftime("%Y-%m")

        by_strategy_period[trade.strategy_id][period_key] += trade.pnl

    # Convert to return lists (sorted by period)
    results: dict[str, list[float]] = {}

    for strategy_id, periods in by_strategy_period.items():
        sorted_periods = sorted(periods.keys())
        # Convert P&L to approximate returns (assuming constant capital)
        # In practice, you'd want actual equity for each period
        returns = [float(periods[p]) for p in sorted_periods]
        results[strategy_id] = returns

    return results


def calculate_correlation_matrix(
    strategy_returns: dict[str, list[float]],
) -> dict[tuple[str, str], float]:
    """Calculate pairwise correlation between strategy returns.

    Args:
        strategy_returns: Dict of strategy_id -> list of returns

    Returns:
        Dictionary mapping (strategy_a, strategy_b) -> correlation
    """
    strategies = list(strategy_returns.keys())
    correlations: dict[tuple[str, str], float] = {}

    for i, strat_a in enumerate(strategies):
        for strat_b in strategies[i:]:
            if strat_a == strat_b:
                correlations[(strat_a, strat_b)] = 1.0
            else:
                corr = _pearson_correlation(
                    strategy_returns[strat_a],
                    strategy_returns[strat_b],
                )
                correlations[(strat_a, strat_b)] = corr
                correlations[(strat_b, strat_a)] = corr

    return correlations


def _pearson_correlation(x: list[float], y: list[float]) -> float:
    """Calculate Pearson correlation coefficient.

    Args:
        x: First series
        y: Second series (must be same length)

    Returns:
        Correlation coefficient (-1 to 1), or 0 if cannot calculate
    """
    if len(x) != len(y) or len(x) < 2:
        return 0.0

    n = len(x)
    mean_x = sum(x) / n
    mean_y = sum(y) / n

    # Covariance
    cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n)) / (n - 1)

    # Standard deviations
    std_x = (sum((xi - mean_x) ** 2 for xi in x) / (n - 1)) ** 0.5
    std_y = (sum((yi - mean_y) ** 2 for yi in y) / (n - 1)) ** 0.5

    if std_x == 0 or std_y == 0:
        return 0.0

    return cov / (std_x * std_y)


@dataclass
class PortfolioSummary:
    """Summary analytics for entire portfolio."""

    total_pnl: Decimal
    total_trades: int
    overall_win_rate: float
    overall_profit_factor: float
    overall_sharpe: float | None
    overall_sortino: float | None
    max_drawdown: float
    best_strategy: str | None
    worst_strategy: str | None
    strategy_count: int
    avg_correlation: float | None


def calculate_portfolio_summary(
    trades: list[TradeRecord],
    equity_curve: list[Decimal] | None = None,
) -> PortfolioSummary:
    """Calculate overall portfolio analytics.

    Args:
        trades: All trades across strategies
        equity_curve: Optional portfolio equity curve

    Returns:
        PortfolioSummary with aggregate metrics
    """
    if not trades:
        return PortfolioSummary(
            total_pnl=Decimal("0"),
            total_trades=0,
            overall_win_rate=0.0,
            overall_profit_factor=0.0,
            overall_sharpe=None,
            overall_sortino=None,
            max_drawdown=0.0,
            best_strategy=None,
            worst_strategy=None,
            strategy_count=0,
            avg_correlation=None,
        )

    stats = calculate_trade_stats(trades)

    # Risk metrics from equity curve
    sharpe = None
    sortino = None
    max_dd = 0.0

    if equity_curve and len(equity_curve) > 1:
        from .metrics import returns_from_equity

        returns = returns_from_equity([float(e) for e in equity_curve])
        if returns:
            sharpe = calculate_sharpe_ratio(returns)
            sortino = calculate_sortino_ratio(returns)
        max_dd = calculate_max_drawdown(equity_curve)

    # Strategy performance
    strategy_perf = calculate_strategy_performance(trades)
    strategy_pnl = {s: p.total_pnl for s, p in strategy_perf.items()}

    best = max(strategy_pnl, key=strategy_pnl.get) if strategy_pnl else None
    worst = min(strategy_pnl, key=strategy_pnl.get) if strategy_pnl else None

    # Average correlation
    avg_corr = None
    if len(strategy_perf) > 1:
        strategy_returns = calculate_strategy_returns(trades)
        if all(len(r) > 1 for r in strategy_returns.values()):
            correlations = calculate_correlation_matrix(strategy_returns)
            # Average off-diagonal correlations
            off_diag = [
                v for (a, b), v in correlations.items() if a != b
            ]
            if off_diag:
                avg_corr = sum(off_diag) / len(off_diag)

    return PortfolioSummary(
        total_pnl=stats.total_pnl,
        total_trades=stats.total_trades,
        overall_win_rate=stats.win_rate,
        overall_profit_factor=stats.profit_factor,
        overall_sharpe=sharpe,
        overall_sortino=sortino,
        max_drawdown=max_dd,
        best_strategy=best,
        worst_strategy=worst,
        strategy_count=len(strategy_perf),
        avg_correlation=avg_corr,
    )
