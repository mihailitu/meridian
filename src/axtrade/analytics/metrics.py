"""Rolling performance metrics calculations."""

import math
from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass
class RollingMetrics:
    """Container for rolling performance metrics."""

    sharpe_ratio: float | None
    sortino_ratio: float | None
    volatility: float | None
    annualized_return: float | None
    window_days: int
    data_points: int
    calculated_at: datetime


def calculate_sharpe_ratio(
    returns: list[float],
    risk_free_rate: float = 0.0,
    annualization_factor: float = 252.0,
) -> float | None:
    """Calculate Sharpe ratio from a series of returns.

    Sharpe = (mean_return - risk_free_rate) / std_dev * sqrt(annualization)

    Args:
        returns: List of periodic returns (e.g., daily returns as decimals)
        risk_free_rate: Risk-free rate for the same period (e.g., daily)
        annualization_factor: Factor to annualize (252 for daily, 12 for monthly)

    Returns:
        Annualized Sharpe ratio, or None if insufficient data
    """
    if len(returns) < 2:
        return None

    excess_returns = [r - risk_free_rate for r in returns]
    mean_excess = sum(excess_returns) / len(excess_returns)

    variance = sum((r - mean_excess) ** 2 for r in excess_returns) / (len(excess_returns) - 1)
    std_dev = math.sqrt(variance)

    if std_dev == 0:
        return None

    sharpe = (mean_excess / std_dev) * math.sqrt(annualization_factor)
    return sharpe


def calculate_sortino_ratio(
    returns: list[float],
    risk_free_rate: float = 0.0,
    annualization_factor: float = 252.0,
    target_return: float = 0.0,
) -> float | None:
    """Calculate Sortino ratio from a series of returns.

    Sortino = (mean_return - target) / downside_deviation * sqrt(annualization)

    Uses only negative deviations from target for risk calculation.

    Args:
        returns: List of periodic returns (e.g., daily returns as decimals)
        risk_free_rate: Risk-free rate for the same period
        annualization_factor: Factor to annualize (252 for daily)
        target_return: Target return (often 0 or risk-free rate)

    Returns:
        Annualized Sortino ratio, or None if insufficient data
    """
    if len(returns) < 2:
        return None

    excess_returns = [r - risk_free_rate for r in returns]
    mean_excess = sum(excess_returns) / len(excess_returns)

    # Calculate downside deviation (only negative deviations from target)
    downside_returns = [min(0, r - target_return) for r in returns]
    downside_variance = sum(r ** 2 for r in downside_returns) / len(downside_returns)
    downside_dev = math.sqrt(downside_variance)

    if downside_dev == 0:
        # No downside risk - return high positive value or None
        return None if mean_excess <= 0 else float('inf')

    sortino = (mean_excess / downside_dev) * math.sqrt(annualization_factor)
    return sortino


def calculate_volatility(
    returns: list[float],
    annualization_factor: float = 252.0,
) -> float | None:
    """Calculate annualized volatility from returns.

    Args:
        returns: List of periodic returns
        annualization_factor: Factor to annualize

    Returns:
        Annualized volatility as decimal, or None if insufficient data
    """
    if len(returns) < 2:
        return None

    mean_return = sum(returns) / len(returns)
    variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
    std_dev = math.sqrt(variance)

    return std_dev * math.sqrt(annualization_factor)


def calculate_annualized_return(
    returns: list[float],
    annualization_factor: float = 252.0,
) -> float | None:
    """Calculate annualized return from periodic returns.

    Uses geometric mean for compounding.

    Args:
        returns: List of periodic returns as decimals
        annualization_factor: Periods per year

    Returns:
        Annualized return as decimal, or None if insufficient data
    """
    if len(returns) < 1:
        return None

    # Calculate cumulative return
    cumulative = 1.0
    for r in returns:
        cumulative *= (1 + r)

    # Annualize based on number of periods
    periods = len(returns)
    if periods < annualization_factor:
        # Less than a year of data - extrapolate
        annualized = cumulative ** (annualization_factor / periods) - 1
    else:
        # Use actual compound growth rate
        annualized = cumulative ** (annualization_factor / periods) - 1

    return annualized


def calculate_calmar_ratio(
    annualized_return: float,
    max_drawdown: float,
) -> float | None:
    """Calculate Calmar ratio (return / max drawdown).

    Args:
        annualized_return: Annualized return as decimal
        max_drawdown: Maximum drawdown as positive decimal (e.g., 0.15 for 15%)

    Returns:
        Calmar ratio, or None if max_drawdown is zero
    """
    if max_drawdown == 0:
        return None

    return annualized_return / max_drawdown


def calculate_rolling_metrics(
    returns: list[float],
    window_days: int = 30,
    risk_free_rate: float = 0.0,
    annualization_factor: float = 252.0,
) -> RollingMetrics:
    """Calculate all rolling metrics for a given window.

    Args:
        returns: List of periodic returns (most recent last)
        window_days: Number of periods to include
        risk_free_rate: Risk-free rate per period
        annualization_factor: Periods per year

    Returns:
        RollingMetrics with all calculated values
    """
    # Take only the window
    window_returns = returns[-window_days:] if len(returns) > window_days else returns

    return RollingMetrics(
        sharpe_ratio=calculate_sharpe_ratio(
            window_returns, risk_free_rate, annualization_factor
        ),
        sortino_ratio=calculate_sortino_ratio(
            window_returns, risk_free_rate, annualization_factor
        ),
        volatility=calculate_volatility(window_returns, annualization_factor),
        annualized_return=calculate_annualized_return(
            window_returns, annualization_factor
        ),
        window_days=window_days,
        data_points=len(window_returns),
        calculated_at=datetime.now(timezone.utc),
    )


def returns_from_equity(equity_values: list[float]) -> list[float]:
    """Convert equity curve to returns.

    Args:
        equity_values: List of equity values (e.g., daily NAV)

    Returns:
        List of periodic returns (one less than input)
    """
    if len(equity_values) < 2:
        return []

    returns = []
    for i in range(1, len(equity_values)):
        if equity_values[i - 1] != 0:
            ret = (equity_values[i] - equity_values[i - 1]) / equity_values[i - 1]
            returns.append(ret)

    return returns
