"""Unit tests for ATR indicator."""

import pytest

from axtrade.indicators import calculate_atr, calculate_atr_smoothed, calculate_true_range


class TestCalculateTrueRange:
    """Tests for calculate_true_range function."""

    def test_high_low_range(self) -> None:
        # High-Low is the largest
        tr = calculate_true_range(high=110.0, low=100.0, prev_close=105.0)
        assert tr == 10.0

    def test_high_prev_close_range(self) -> None:
        # Gap up: high - prev_close is largest
        tr = calculate_true_range(high=120.0, low=115.0, prev_close=100.0)
        assert tr == 20.0  # |120 - 100|

    def test_low_prev_close_range(self) -> None:
        # Gap down: prev_close - low is largest
        tr = calculate_true_range(high=95.0, low=90.0, prev_close=110.0)
        assert tr == 20.0  # |90 - 110|

    def test_no_gap(self) -> None:
        # Normal day, no gap
        tr = calculate_true_range(high=102.0, low=98.0, prev_close=100.0)
        assert tr == 4.0  # high - low


class TestCalculateATR:
    """Tests for calculate_atr function."""

    def test_insufficient_data(self) -> None:
        highs = [100.0, 101.0, 102.0]
        lows = [99.0, 100.0, 101.0]
        closes = [100.0, 101.0, 102.0]
        result = calculate_atr(highs, lows, closes, period=14)
        assert result is None

    def test_mismatched_lengths(self) -> None:
        highs = [100.0] * 20
        lows = [99.0] * 19  # One less
        closes = [100.0] * 20
        result = calculate_atr(highs, lows, closes, period=14)
        assert result is None

    def test_exact_period_data(self) -> None:
        # Need period + 1 bars (TR needs prev close)
        n = 15
        highs = [100.0 + i for i in range(n)]
        lows = [99.0 + i for i in range(n)]
        closes = [99.5 + i for i in range(n)]

        result = calculate_atr(highs, lows, closes, period=14)
        assert result is not None
        assert result > 0

    def test_constant_range(self) -> None:
        # Each bar has same high-low range of 2
        n = 20
        highs = [101.0] * n
        lows = [99.0] * n
        closes = [100.0] * n

        result = calculate_atr(highs, lows, closes, period=14)
        assert result is not None
        # All TRs should be 2 (high - low, no gaps)
        assert result == pytest.approx(2.0, rel=0.01)

    def test_increasing_volatility(self) -> None:
        # Volatility increases over time
        n = 20
        highs = [100.0 + i * 0.5 for i in range(n)]  # Increasing highs
        lows = [100.0 - i * 0.5 for i in range(n)]  # Decreasing lows
        closes = [100.0 for i in range(n)]  # Flat closes

        result = calculate_atr(highs, lows, closes, period=14)
        assert result is not None
        # ATR should reflect the increasing range
        assert result > 5.0


class TestCalculateATRSmoothed:
    """Tests for calculate_atr_smoothed function."""

    def test_insufficient_data(self) -> None:
        highs = [100.0] * 10
        lows = [99.0] * 10
        closes = [100.0] * 10
        result = calculate_atr_smoothed(highs, lows, closes, period=14)
        assert result is None

    def test_smoothed_vs_simple(self) -> None:
        # Smoothed ATR should differ from simple ATR
        n = 30
        highs = [100.0 + (i % 3) for i in range(n)]
        lows = [99.0 + (i % 3) for i in range(n)]
        closes = [99.5 + (i % 3) for i in range(n)]

        simple = calculate_atr(highs, lows, closes, period=14)
        smoothed = calculate_atr_smoothed(highs, lows, closes, period=14)

        assert simple is not None
        assert smoothed is not None
        # Both should be positive
        assert simple > 0
        assert smoothed > 0

    def test_smoothed_reduces_volatility(self) -> None:
        # Smoothed ATR should be less reactive to recent changes
        n = 25
        # Stable period then volatile period
        highs = [101.0] * 15 + [110.0] * 10
        lows = [99.0] * 15 + [90.0] * 10
        closes = [100.0] * 15 + [100.0] * 10

        simple = calculate_atr(highs, lows, closes, period=14)
        smoothed = calculate_atr_smoothed(highs, lows, closes, period=14)

        assert simple is not None
        assert smoothed is not None
        # Simple ATR uses only last 14 TRs (all volatile)
        # Smoothed carries forward the stable period
        # So smoothed should be lower
        assert smoothed < simple
