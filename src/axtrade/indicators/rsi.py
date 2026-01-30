"""Relative Strength Index calculation."""

from collections import deque
from typing import Optional


def calculate_rsi(prices: list[float] | deque[float], period: int) -> Optional[float]:
    """Calculate Relative Strength Index using Wilder's smoothing.

    Args:
        prices: List of prices (most recent last)
        period: RSI period (typically 14)

    Returns:
        RSI value (0-100) if enough data, None otherwise
    """
    # Need at least period + 1 prices to calculate period changes
    if len(prices) < period + 1:
        return None

    prices_list = list(prices)

    # Calculate price changes
    changes = [
        prices_list[i] - prices_list[i - 1]
        for i in range(1, len(prices_list))
    ]

    # Separate gains and losses
    gains = [max(0, c) for c in changes]
    losses = [max(0, -c) for c in changes]

    # Initial average gain/loss using SMA for first period
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Apply Wilder's smoothing for remaining periods
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    # Calculate RSI
    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))

    return round(rsi, 4)
