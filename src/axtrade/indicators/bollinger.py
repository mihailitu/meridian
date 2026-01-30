"""Bollinger Bands indicator calculation."""


def calculate_bollinger_bands(
    prices: list[float],
    period: int = 20,
    num_std: float = 2.0,
) -> tuple[float, float, float] | None:
    """Calculate Bollinger Bands.

    Bollinger Bands consist of:
    - Middle band: Simple moving average
    - Upper band: SMA + (num_std * standard deviation)
    - Lower band: SMA - (num_std * standard deviation)

    Args:
        prices: List of closing prices
        period: Lookback period for SMA and std dev
        num_std: Number of standard deviations for bands

    Returns:
        Tuple of (middle, upper, lower) band values, or None if insufficient data
    """
    if len(prices) < period:
        return None

    window = prices[-period:]
    middle = sum(window) / period

    # Calculate standard deviation
    variance = sum((p - middle) ** 2 for p in window) / period
    std_dev = variance ** 0.5

    upper = middle + (num_std * std_dev)
    lower = middle - (num_std * std_dev)

    return (middle, upper, lower)


def calculate_bollinger_bandwidth(
    prices: list[float],
    period: int = 20,
    num_std: float = 2.0,
) -> float | None:
    """Calculate Bollinger Bandwidth.

    Bandwidth = (Upper - Lower) / Middle * 100
    Used to measure volatility - lower values indicate consolidation.

    Args:
        prices: List of closing prices
        period: Lookback period
        num_std: Number of standard deviations

    Returns:
        Bandwidth percentage, or None if insufficient data
    """
    bands = calculate_bollinger_bands(prices, period, num_std)
    if bands is None:
        return None

    middle, upper, lower = bands
    if middle == 0:
        return None

    return ((upper - lower) / middle) * 100


def calculate_percent_b(
    prices: list[float],
    period: int = 20,
    num_std: float = 2.0,
) -> float | None:
    """Calculate %B indicator.

    %B = (Price - Lower Band) / (Upper Band - Lower Band)
    - Values > 1: Price above upper band
    - Values < 0: Price below lower band
    - Value = 0.5: Price at middle band

    Args:
        prices: List of closing prices
        period: Lookback period
        num_std: Number of standard deviations

    Returns:
        %B value, or None if insufficient data
    """
    if not prices:
        return None

    bands = calculate_bollinger_bands(prices, period, num_std)
    if bands is None:
        return None

    middle, upper, lower = bands
    band_width = upper - lower

    if band_width == 0:
        return None

    current_price = prices[-1]
    return (current_price - lower) / band_width
