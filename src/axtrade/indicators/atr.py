"""Average True Range (ATR) indicator calculation."""


def calculate_true_range(
    high: float,
    low: float,
    prev_close: float,
) -> float:
    """Calculate True Range for a single bar.

    True Range is the greatest of:
    - Current high minus current low
    - Absolute value of current high minus previous close
    - Absolute value of current low minus previous close

    Args:
        high: Current bar's high price
        low: Current bar's low price
        prev_close: Previous bar's close price

    Returns:
        True Range value
    """
    return max(
        high - low,
        abs(high - prev_close),
        abs(low - prev_close),
    )


def calculate_atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> float | None:
    """Calculate Average True Range.

    ATR is the average of True Range values over the specified period.
    Uses simple moving average (Wilder originally used smoothed average).

    Args:
        highs: List of high prices
        lows: List of low prices
        closes: List of close prices
        period: Lookback period (default 14)

    Returns:
        ATR value, or None if insufficient data
    """
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return None

    if len(highs) != len(lows) or len(highs) != len(closes):
        return None

    # Calculate True Range for each bar (starting from index 1)
    true_ranges = []
    for i in range(1, len(highs)):
        tr = calculate_true_range(highs[i], lows[i], closes[i - 1])
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    # Simple average of last 'period' true ranges
    return sum(true_ranges[-period:]) / period


def calculate_atr_smoothed(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int = 14,
) -> float | None:
    """Calculate ATR using Wilder's smoothing method.

    This is the original ATR calculation method using exponential smoothing:
    ATR = ((prior ATR * (period - 1)) + current TR) / period

    Args:
        highs: List of high prices
        lows: List of low prices
        closes: List of close prices
        period: Lookback period (default 14)

    Returns:
        Smoothed ATR value, or None if insufficient data
    """
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return None

    if len(highs) != len(lows) or len(highs) != len(closes):
        return None

    # Calculate all True Ranges
    true_ranges = []
    for i in range(1, len(highs)):
        tr = calculate_true_range(highs[i], lows[i], closes[i - 1])
        true_ranges.append(tr)

    if len(true_ranges) < period:
        return None

    # Initial ATR is simple average of first 'period' TRs
    atr = sum(true_ranges[:period]) / period

    # Apply Wilder's smoothing for remaining TRs
    for tr in true_ranges[period:]:
        atr = ((atr * (period - 1)) + tr) / period

    return atr
