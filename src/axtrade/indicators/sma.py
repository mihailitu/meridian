"""Simple Moving Average calculation."""

from collections import deque
from typing import Optional


def calculate_sma(prices: list[float] | deque[float], period: int) -> Optional[float]:
    """Calculate Simple Moving Average.

    Args:
        prices: List of prices (most recent last)
        period: Number of periods for average

    Returns:
        SMA value if enough data, None otherwise
    """
    if len(prices) < period:
        return None

    # Take the last 'period' prices
    recent = list(prices)[-period:]
    return sum(recent) / period
