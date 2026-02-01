"""Unit tests for market regime detection."""

import pytest

from axtrade.indicators import (
    MarketRegime,
    MarketTrend,
    RegimeEngine,
    VolatilityState,
    calculate_regime,
    calculate_trend,
    calculate_volatility,
)
from axtrade.indicators.engine import IndicatorEngine


class TestCalculateTrend:
    """Tests for trend calculation."""

    def test_bullish_trend_upward_prices(self) -> None:
        """Upward trending prices should be bullish."""
        prices = [100.0 + i * 0.5 for i in range(30)]
        trend, strength = calculate_trend(prices)
        assert trend == MarketTrend.BULLISH
        assert strength > 0

    def test_bearish_trend_downward_prices(self) -> None:
        """Downward trending prices should be bearish."""
        prices = [100.0 - i * 0.5 for i in range(30)]
        trend, strength = calculate_trend(prices)
        assert trend == MarketTrend.BEARISH
        assert strength > 0

    def test_neutral_trend_flat_prices(self) -> None:
        """Flat prices should be neutral or weak trend."""
        prices = [100.0] * 30
        trend, strength = calculate_trend(prices)
        # Flat prices result in neutral trend
        assert trend == MarketTrend.NEUTRAL or strength < 20

    def test_insufficient_data_returns_neutral(self) -> None:
        """Insufficient data should return neutral trend."""
        prices = [100.0, 101.0, 102.0]  # Less than sma_long_period
        trend, strength = calculate_trend(prices)
        assert trend == MarketTrend.NEUTRAL
        assert strength == 0.0

    def test_alternating_prices_weak_trend(self) -> None:
        """Alternating prices should have weak or neutral trend."""
        prices = []
        for i in range(30):
            prices.append(100.0 + (1 if i % 2 == 0 else -1))
        trend, strength = calculate_trend(prices)
        # Should not show strong bullish or bearish
        assert strength < 50

    def test_custom_periods(self) -> None:
        """Custom SMA periods should work correctly."""
        prices = [100.0 + i for i in range(40)]
        trend, strength = calculate_trend(prices, sma_short_period=5, sma_long_period=15)
        assert trend == MarketTrend.BULLISH

    def test_trend_strength_capped_at_100(self) -> None:
        """Trend strength should be capped at 100."""
        # Very strong uptrend
        prices = [100.0 + i * 5 for i in range(30)]
        trend, strength = calculate_trend(prices)
        assert strength <= 100.0


class TestCalculateVolatility:
    """Tests for volatility calculation."""

    def test_low_volatility_stable_prices(self) -> None:
        """Stable prices should have low volatility."""
        prices = [100.0 + i * 0.01 for i in range(30)]  # Very small changes
        state, percentile, atr_ratio = calculate_volatility(prices)
        assert state == VolatilityState.LOW
        assert percentile < 30

    def test_high_volatility_erratic_prices(self) -> None:
        """Large price swings should have high volatility."""
        prices = []
        for i in range(30):
            prices.append(100.0 + (10 if i % 2 == 0 else -10))
        state, percentile, atr_ratio = calculate_volatility(prices)
        assert state in (VolatilityState.HIGH, VolatilityState.EXTREME)
        assert percentile > 50

    def test_volatility_with_ohlc_data(self) -> None:
        """Volatility calculation with OHLC data should include ATR ratio."""
        closes = [100.0 + i * 0.1 for i in range(30)]
        highs = [c + 1 for c in closes]
        lows = [c - 1 for c in closes]
        state, percentile, atr_ratio = calculate_volatility(closes, highs, lows)
        assert atr_ratio is not None
        assert atr_ratio > 0

    def test_insufficient_data_returns_normal(self) -> None:
        """Insufficient data should return normal volatility."""
        prices = [100.0, 101.0, 102.0]
        state, percentile, atr_ratio = calculate_volatility(prices)
        assert state == VolatilityState.NORMAL
        assert percentile == 50.0

    def test_volatility_percentile_bounded(self) -> None:
        """Volatility percentile should be between 0 and 100."""
        prices = [100.0 + i * 2 for i in range(30)]
        state, percentile, atr_ratio = calculate_volatility(prices)
        assert 0 <= percentile <= 100


class TestCalculateRegime:
    """Tests for combined regime calculation."""

    def test_trending_up_regime(self) -> None:
        """Strong uptrend with low volatility should be trending_up."""
        closes = [100.0 + i * 0.3 for i in range(50)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        result = calculate_regime(closes, highs, lows)
        assert result is not None
        assert result.regime == MarketRegime.TRENDING_UP
        assert result.trend == MarketTrend.BULLISH

    def test_trending_down_regime(self) -> None:
        """Strong downtrend with low volatility should be trending_down."""
        closes = [100.0 - i * 0.3 for i in range(50)]
        highs = [c + 0.5 for c in closes]
        lows = [c - 0.5 for c in closes]
        result = calculate_regime(closes, highs, lows)
        assert result is not None
        assert result.regime == MarketRegime.TRENDING_DOWN
        assert result.trend == MarketTrend.BEARISH

    def test_ranging_quiet_regime(self) -> None:
        """Neutral trend with low volatility should be ranging_quiet."""
        # Perfect symmetrical oscillations around a mean
        closes = []
        for i in range(50):
            # Create a sine-wave pattern around 100 with small amplitude
            import math
            closes.append(100.0 + 0.05 * math.sin(i * 0.5))
        highs = [c + 0.05 for c in closes]
        lows = [c - 0.05 for c in closes]
        result = calculate_regime(closes, highs, lows)
        assert result is not None
        # With a perfectly oscillating pattern, trend should be neutral
        assert result.trend == MarketTrend.NEUTRAL
        assert result.regime == MarketRegime.RANGING_QUIET

    def test_ranging_volatile_regime(self) -> None:
        """Neutral trend with high volatility should be ranging_volatile."""
        # Large oscillations
        closes = [100.0 + (5 if i % 4 < 2 else -5) for i in range(50)]
        highs = [c + 3 for c in closes]
        lows = [c - 3 for c in closes]
        result = calculate_regime(closes, highs, lows)
        assert result is not None
        assert result.regime == MarketRegime.RANGING_VOLATILE

    def test_insufficient_data_returns_none(self) -> None:
        """Insufficient data should return None."""
        closes = [100.0, 101.0, 102.0]
        result = calculate_regime(closes)
        assert result is None

    def test_regime_result_fields(self) -> None:
        """Regime result should have all required fields."""
        closes = [100.0 + i * 0.2 for i in range(50)]
        result = calculate_regime(closes)
        assert result is not None
        assert result.regime is not None
        assert result.trend is not None
        assert result.volatility is not None
        assert result.trend_strength is not None
        assert result.volatility_percentile is not None


class TestRegimeEngine:
    """Tests for RegimeEngine class."""

    def test_process_bar_accumulates_data(self) -> None:
        """Processing bars should accumulate price data."""
        engine = RegimeEngine()
        for i in range(10):
            engine.process_bar("AAPL", "1m", 100.0, 101.0, 99.0, 100.5 + i * 0.1)
        assert engine.get_buffer_size("AAPL", "1m") == 10

    def test_process_bar_returns_result_with_enough_data(self) -> None:
        """Should return regime result when enough data is accumulated."""
        engine = RegimeEngine()
        result = None
        for i in range(30):
            result = engine.process_bar("AAPL", "1m", 100.0 + i * 0.2, 101.0 + i * 0.2, 99.0 + i * 0.2, 100.5 + i * 0.2)
        assert result is not None
        assert result.regime is not None

    def test_separate_buffers_per_symbol(self) -> None:
        """Different symbols should have separate buffers."""
        engine = RegimeEngine()
        for i in range(10):
            engine.process_bar("AAPL", "1m", 100.0, 101.0, 99.0, 100.5)
            engine.process_bar("MSFT", "1m", 200.0, 201.0, 199.0, 200.5)
        assert engine.get_buffer_size("AAPL", "1m") == 10
        assert engine.get_buffer_size("MSFT", "1m") == 10

    def test_separate_buffers_per_interval(self) -> None:
        """Different intervals should have separate buffers."""
        engine = RegimeEngine()
        for i in range(10):
            engine.process_bar("AAPL", "1m", 100.0, 101.0, 99.0, 100.5)
        for i in range(5):
            engine.process_bar("AAPL", "5m", 100.0, 101.0, 99.0, 100.5)
        assert engine.get_buffer_size("AAPL", "1m") == 10
        assert engine.get_buffer_size("AAPL", "5m") == 5

    def test_initialize_buffer(self) -> None:
        """Buffer initialization should populate historical data."""
        engine = RegimeEngine()
        closes = [100.0 + i * 0.1 for i in range(50)]
        highs = [c + 1 for c in closes]
        lows = [c - 1 for c in closes]
        engine.initialize_buffer("AAPL", "1m", closes, highs, lows)
        assert engine.get_buffer_size("AAPL", "1m") == 50

        # First new bar should calculate regime
        result = engine.process_bar("AAPL", "1m", 106.0, 107.0, 105.0, 106.0)
        assert result is not None

    def test_get_regime_returns_cached_result(self) -> None:
        """get_regime should return the last calculated result."""
        engine = RegimeEngine()
        for i in range(30):
            engine.process_bar("AAPL", "1m", 100.0 + i * 0.2, 101.0 + i * 0.2, 99.0 + i * 0.2, 100.5 + i * 0.2)
        result = engine.get_regime("AAPL", "1m")
        assert result is not None

    def test_get_regime_returns_none_without_data(self) -> None:
        """get_regime should return None for unknown symbol/interval."""
        engine = RegimeEngine()
        result = engine.get_regime("UNKNOWN", "1m")
        assert result is None

    def test_buffer_rolls_over(self) -> None:
        """Buffer should roll over when exceeding max size."""
        engine = RegimeEngine(buffer_size=50)
        for i in range(100):
            engine.process_bar("AAPL", "1m", 100.0, 101.0, 99.0, 100.5 + i * 0.01)
        assert engine.get_buffer_size("AAPL", "1m") == 50


class TestIndicatorEngineWithRegime:
    """Tests for IndicatorEngine with regime integration."""

    def test_process_bar_returns_regime(self) -> None:
        """IndicatorEngine should include regime in result."""
        engine = IndicatorEngine(sma_period=5, rsi_period=5)
        result = None
        for i in range(30):
            result = engine.process_bar("AAPL", "1m", 100.0 + i * 0.2, high=101.0 + i * 0.2, low=99.0 + i * 0.2)
        assert result is not None
        assert result.regime is not None
        assert result.trend is not None
        assert result.volatility is not None

    def test_process_bar_without_ohlc_still_calculates_regime(self) -> None:
        """IndicatorEngine should calculate regime with just close prices."""
        engine = IndicatorEngine(sma_period=5, rsi_period=5)
        result = None
        for i in range(30):
            result = engine.process_bar("AAPL", "1m", 100.0 + i * 0.2)
        assert result is not None
        assert result.regime is not None

    def test_indicator_result_has_all_fields(self) -> None:
        """IndicatorResult should have all indicator and regime fields."""
        engine = IndicatorEngine(sma_period=5, rsi_period=5)
        for i in range(30):
            result = engine.process_bar("AAPL", "1m", 100.0 + i * 0.2, high=101.0 + i * 0.2, low=99.0 + i * 0.2)

        assert result.sma_20 is not None
        assert result.rsi_14 is not None
        assert result.regime is not None
        assert result.trend is not None
        assert result.volatility is not None
        assert result.trend_strength is not None
        assert result.volatility_percentile is not None

    def test_initialize_buffer_with_ohlc(self) -> None:
        """IndicatorEngine buffer initialization should support OHLC data."""
        engine = IndicatorEngine(sma_period=5, rsi_period=5)
        closes = [100.0 + i * 0.1 for i in range(30)]
        highs = [c + 1 for c in closes]
        lows = [c - 1 for c in closes]
        engine.initialize_buffer("AAPL", "1m", closes, highs, lows)

        # First new bar should have regime
        result = engine.process_bar("AAPL", "1m", 104.0, high=105.0, low=103.0)
        assert result.regime is not None


class TestMarketRegimeEnum:
    """Tests for MarketRegime enum values."""

    def test_all_regime_values(self) -> None:
        """All expected regime values should exist."""
        assert MarketRegime.TRENDING_UP.value == "trending_up"
        assert MarketRegime.TRENDING_DOWN.value == "trending_down"
        assert MarketRegime.RANGING_QUIET.value == "ranging_quiet"
        assert MarketRegime.RANGING_VOLATILE.value == "ranging_volatile"
        assert MarketRegime.BREAKOUT.value == "breakout"
        assert MarketRegime.BREAKDOWN.value == "breakdown"

    def test_trend_values(self) -> None:
        """All expected trend values should exist."""
        assert MarketTrend.BULLISH.value == "bullish"
        assert MarketTrend.BEARISH.value == "bearish"
        assert MarketTrend.NEUTRAL.value == "neutral"

    def test_volatility_values(self) -> None:
        """All expected volatility values should exist."""
        assert VolatilityState.LOW.value == "low"
        assert VolatilityState.NORMAL.value == "normal"
        assert VolatilityState.HIGH.value == "high"
        assert VolatilityState.EXTREME.value == "extreme"
