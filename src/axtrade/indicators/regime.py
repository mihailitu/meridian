"""Market regime detection based on trend and volatility analysis."""

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class MarketTrend(Enum):
    """Market trend direction."""

    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class VolatilityState(Enum):
    """Market volatility state."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    EXTREME = "extreme"


class MarketRegime(Enum):
    """Combined market regime classification."""

    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING_QUIET = "ranging_quiet"
    RANGING_VOLATILE = "ranging_volatile"
    BREAKOUT = "breakout"
    BREAKDOWN = "breakdown"


@dataclass
class RegimeResult:
    """Result of regime analysis."""

    regime: MarketRegime
    trend: MarketTrend
    volatility: VolatilityState
    trend_strength: float  # 0-100 scale
    volatility_percentile: float  # 0-100 scale
    atr_ratio: Optional[float] = None  # ATR / price ratio


def calculate_trend(
    closes: list[float],
    sma_short_period: int = 10,
    sma_long_period: int = 20,
) -> tuple[MarketTrend, float]:
    """Calculate trend direction and strength.

    Uses dual SMA crossover with price position relative to moving averages.

    Args:
        closes: List of closing prices (oldest first)
        sma_short_period: Period for short-term SMA
        sma_long_period: Period for long-term SMA

    Returns:
        Tuple of (trend direction, trend strength 0-100)
    """
    if len(closes) < sma_long_period:
        return MarketTrend.NEUTRAL, 0.0

    recent = closes[-sma_long_period:]
    sma_short = sum(recent[-sma_short_period:]) / sma_short_period
    sma_long = sum(recent) / sma_long_period
    current_price = closes[-1]

    # Calculate percentage difference between SMAs
    if sma_long == 0:
        return MarketTrend.NEUTRAL, 0.0

    sma_diff_pct = (sma_short - sma_long) / sma_long * 100

    # Price position relative to both SMAs
    price_vs_short = (current_price - sma_short) / sma_short * 100 if sma_short else 0
    price_vs_long = (current_price - sma_long) / sma_long * 100

    # Combined strength score
    strength = abs(sma_diff_pct) * 10 + abs(price_vs_short) * 2 + abs(price_vs_long) * 3
    strength = min(strength, 100.0)  # Cap at 100

    # Determine trend direction
    if sma_short > sma_long and current_price > sma_short:
        trend = MarketTrend.BULLISH
    elif sma_short < sma_long and current_price < sma_short:
        trend = MarketTrend.BEARISH
    else:
        trend = MarketTrend.NEUTRAL
        strength = strength * 0.5  # Reduce strength for neutral trend

    return trend, round(strength, 2)


def calculate_volatility(
    closes: list[float],
    highs: Optional[list[float]] = None,
    lows: Optional[list[float]] = None,
    lookback: int = 20,
    atr_period: int = 14,
) -> tuple[VolatilityState, float, Optional[float]]:
    """Calculate volatility state and metrics.

    Uses standard deviation of returns and optionally ATR.

    Args:
        closes: List of closing prices (oldest first)
        highs: Optional list of high prices for ATR calculation
        lows: Optional list of low prices for ATR calculation
        lookback: Lookback period for volatility calculation
        atr_period: Period for ATR calculation

    Returns:
        Tuple of (volatility state, percentile 0-100, ATR ratio or None)
    """
    if len(closes) < lookback + 1:
        return VolatilityState.NORMAL, 50.0, None

    # Calculate returns
    returns = []
    for i in range(len(closes) - lookback, len(closes)):
        if closes[i - 1] != 0:
            ret = (closes[i] - closes[i - 1]) / closes[i - 1]
            returns.append(ret)

    if not returns:
        return VolatilityState.NORMAL, 50.0, None

    # Calculate realized volatility (standard deviation of returns)
    mean_return = sum(returns) / len(returns)
    variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
    realized_vol = variance ** 0.5

    # Annualize (assuming daily data, 252 trading days)
    annualized_vol = realized_vol * (252 ** 0.5) * 100  # As percentage

    # Calculate ATR ratio if OHLC data available
    atr_ratio = None
    if highs and lows and len(highs) >= atr_period and len(lows) >= atr_period:
        atr = _calculate_atr(highs, lows, closes, atr_period)
        if atr and closes[-1] != 0:
            atr_ratio = (atr / closes[-1]) * 100  # ATR as % of price

    # Convert to percentile (rough heuristic based on typical market volatility)
    # VIX typical range: 10-40, with 15-20 being "normal"
    percentile = min((annualized_vol / 30.0) * 50, 100.0)

    # Classify volatility state
    if percentile < 25:
        state = VolatilityState.LOW
    elif percentile < 60:
        state = VolatilityState.NORMAL
    elif percentile < 85:
        state = VolatilityState.HIGH
    else:
        state = VolatilityState.EXTREME

    return state, round(percentile, 2), round(atr_ratio, 4) if atr_ratio else None


def _calculate_atr(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    period: int,
) -> Optional[float]:
    """Calculate Average True Range.

    Args:
        highs: List of high prices
        lows: List of low prices
        closes: List of closing prices
        period: ATR period

    Returns:
        ATR value or None if insufficient data
    """
    if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
        return None

    true_ranges = []
    for i in range(-period, 0):
        high = highs[i]
        low = lows[i]
        prev_close = closes[i - 1]

        tr = max(
            high - low,
            abs(high - prev_close),
            abs(low - prev_close),
        )
        true_ranges.append(tr)

    return sum(true_ranges) / len(true_ranges)


def calculate_regime(
    closes: list[float],
    highs: Optional[list[float]] = None,
    lows: Optional[list[float]] = None,
    sma_short_period: int = 10,
    sma_long_period: int = 20,
    volatility_lookback: int = 20,
    atr_period: int = 14,
) -> Optional[RegimeResult]:
    """Calculate comprehensive market regime.

    Combines trend and volatility analysis to classify market conditions.

    Args:
        closes: List of closing prices (oldest first)
        highs: Optional list of high prices for ATR calculation
        lows: Optional list of low prices for ATR calculation
        sma_short_period: Period for short-term SMA in trend calculation
        sma_long_period: Period for long-term SMA in trend calculation
        volatility_lookback: Lookback period for volatility calculation
        atr_period: Period for ATR calculation

    Returns:
        RegimeResult with classification and metrics, or None if insufficient data
    """
    min_data = max(sma_long_period, volatility_lookback + 1)
    if len(closes) < min_data:
        return None

    # Calculate components
    trend, trend_strength = calculate_trend(closes, sma_short_period, sma_long_period)
    volatility_state, vol_percentile, atr_ratio = calculate_volatility(
        closes, highs, lows, volatility_lookback, atr_period
    )

    # Determine regime based on trend + volatility combination
    if trend == MarketTrend.BULLISH:
        if volatility_state in (VolatilityState.HIGH, VolatilityState.EXTREME):
            if trend_strength > 70:
                regime = MarketRegime.BREAKOUT
            else:
                regime = MarketRegime.RANGING_VOLATILE
        else:
            regime = MarketRegime.TRENDING_UP
    elif trend == MarketTrend.BEARISH:
        if volatility_state in (VolatilityState.HIGH, VolatilityState.EXTREME):
            if trend_strength > 70:
                regime = MarketRegime.BREAKDOWN
            else:
                regime = MarketRegime.RANGING_VOLATILE
        else:
            regime = MarketRegime.TRENDING_DOWN
    else:  # Neutral
        if volatility_state in (VolatilityState.LOW, VolatilityState.NORMAL):
            regime = MarketRegime.RANGING_QUIET
        else:
            regime = MarketRegime.RANGING_VOLATILE

    return RegimeResult(
        regime=regime,
        trend=trend,
        volatility=volatility_state,
        trend_strength=trend_strength,
        volatility_percentile=vol_percentile,
        atr_ratio=atr_ratio,
    )


class RegimeEngine:
    """Engine for tracking regime across multiple symbols."""

    def __init__(
        self,
        sma_short_period: int = 10,
        sma_long_period: int = 20,
        volatility_lookback: int = 20,
        atr_period: int = 14,
        buffer_size: int = 100,
    ):
        """Initialize regime engine.

        Args:
            sma_short_period: Period for short-term SMA
            sma_long_period: Period for long-term SMA
            volatility_lookback: Lookback period for volatility
            atr_period: ATR calculation period
            buffer_size: Maximum buffer size for price data
        """
        self.sma_short_period = sma_short_period
        self.sma_long_period = sma_long_period
        self.volatility_lookback = volatility_lookback
        self.atr_period = atr_period
        self.buffer_size = buffer_size

        # Buffers keyed by (symbol, interval)
        self._closes: dict[tuple[str, str], deque[float]] = {}
        self._highs: dict[tuple[str, str], deque[float]] = {}
        self._lows: dict[tuple[str, str], deque[float]] = {}

        # Cache last regime per symbol/interval
        self._last_regime: dict[tuple[str, str], RegimeResult] = {}

    def _get_key(self, symbol: str, interval: str) -> tuple[str, str]:
        """Get buffer key."""
        return (symbol, interval)

    def _ensure_buffers(self, symbol: str, interval: str) -> None:
        """Ensure buffers exist for symbol/interval."""
        key = self._get_key(symbol, interval)
        if key not in self._closes:
            self._closes[key] = deque(maxlen=self.buffer_size)
            self._highs[key] = deque(maxlen=self.buffer_size)
            self._lows[key] = deque(maxlen=self.buffer_size)

    def initialize_buffer(
        self,
        symbol: str,
        interval: str,
        closes: list[float],
        highs: Optional[list[float]] = None,
        lows: Optional[list[float]] = None,
    ) -> None:
        """Initialize buffers with historical data.

        Args:
            symbol: Symbol identifier
            interval: Bar interval
            closes: Historical close prices (oldest first)
            highs: Optional historical high prices
            lows: Optional historical low prices
        """
        self._ensure_buffers(symbol, interval)
        key = self._get_key(symbol, interval)

        self._closes[key].clear()
        self._highs[key].clear()
        self._lows[key].clear()

        for i, close in enumerate(closes):
            self._closes[key].append(close)
            if highs and i < len(highs):
                self._highs[key].append(highs[i])
            if lows and i < len(lows):
                self._lows[key].append(lows[i])

    def process_bar(
        self,
        symbol: str,
        interval: str,
        open_: float,
        high: float,
        low: float,
        close: float,
    ) -> Optional[RegimeResult]:
        """Process a new bar and calculate regime.

        Args:
            symbol: Symbol identifier
            interval: Bar interval
            open_: Opening price
            high: High price
            low: Low price
            close: Closing price

        Returns:
            RegimeResult or None if insufficient data
        """
        self._ensure_buffers(symbol, interval)
        key = self._get_key(symbol, interval)

        # Add to buffers
        self._closes[key].append(close)
        self._highs[key].append(high)
        self._lows[key].append(low)

        # Calculate regime
        closes = list(self._closes[key])
        highs = list(self._highs[key])
        lows = list(self._lows[key])

        result = calculate_regime(
            closes=closes,
            highs=highs,
            lows=lows,
            sma_short_period=self.sma_short_period,
            sma_long_period=self.sma_long_period,
            volatility_lookback=self.volatility_lookback,
            atr_period=self.atr_period,
        )

        if result:
            self._last_regime[key] = result

        return result

    def get_regime(self, symbol: str, interval: str) -> Optional[RegimeResult]:
        """Get last calculated regime for symbol/interval.

        Args:
            symbol: Symbol identifier
            interval: Bar interval

        Returns:
            Last RegimeResult or None
        """
        key = self._get_key(symbol, interval)
        return self._last_regime.get(key)

    def get_buffer_size(self, symbol: str, interval: str) -> int:
        """Get current buffer size for symbol/interval."""
        key = self._get_key(symbol, interval)
        if key in self._closes:
            return len(self._closes[key])
        return 0
