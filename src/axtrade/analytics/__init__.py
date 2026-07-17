"""Performance analytics module."""

from .drawdown import (
    DrawdownInfo,
    DrawdownPeriod,
    DrawdownTracker,
    EquityPoint,
    calculate_max_drawdown,
)
from .metrics import (
    RollingMetrics,
    calculate_annualized_return,
    calculate_calmar_ratio,
    calculate_rolling_metrics,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_volatility,
    returns_from_equity,
)
from .strategy import (
    PortfolioSummary,
    StrategyPerformance,
    calculate_correlation_matrix,
    calculate_portfolio_summary,
    calculate_strategy_performance,
    calculate_strategy_returns,
)
from .trades import (
    TimeAnalysis,
    TradeRecord,
    TradeStats,
    analyze_time_performance,
    calculate_per_symbol_stats,
    calculate_trade_stats,
    pair_fills_fifo,
)

__all__ = [
    "DrawdownInfo",
    "DrawdownPeriod",
    "DrawdownTracker",
    "EquityPoint",
    "PortfolioSummary",
    "RollingMetrics",
    "StrategyPerformance",
    "TimeAnalysis",
    "TradeRecord",
    "TradeStats",
    "analyze_time_performance",
    "calculate_annualized_return",
    "calculate_calmar_ratio",
    "calculate_correlation_matrix",
    "calculate_max_drawdown",
    "calculate_per_symbol_stats",
    "calculate_portfolio_summary",
    "calculate_rolling_metrics",
    "calculate_sharpe_ratio",
    "calculate_sortino_ratio",
    "calculate_strategy_performance",
    "calculate_strategy_returns",
    "calculate_trade_stats",
    "calculate_volatility",
    "pair_fills_fifo",
    "returns_from_equity",
]
