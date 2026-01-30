"""Unit tests for Bollinger Bands indicator."""

import pytest

from axtrade.indicators import (
    calculate_bollinger_bands,
    calculate_bollinger_bandwidth,
    calculate_percent_b,
)


class TestCalculateBollingerBands:
    """Tests for calculate_bollinger_bands function."""

    def test_insufficient_data(self) -> None:
        prices = [100.0, 101.0, 102.0]
        result = calculate_bollinger_bands(prices, period=20)
        assert result is None

    def test_exact_period_data(self) -> None:
        prices = [100.0 + i for i in range(20)]
        result = calculate_bollinger_bands(prices, period=20)
        assert result is not None
        middle, upper, lower = result
        assert middle == pytest.approx(109.5, rel=0.01)
        assert upper > middle
        assert lower < middle

    def test_more_than_period_data(self) -> None:
        prices = [100.0 + i for i in range(30)]
        result = calculate_bollinger_bands(prices, period=20)
        assert result is not None
        middle, upper, lower = result
        # Should use last 20 prices (indices 10-29)
        expected_middle = sum(range(110, 130)) / 20
        assert middle == pytest.approx(expected_middle, rel=0.01)

    def test_constant_prices(self) -> None:
        prices = [100.0] * 25
        result = calculate_bollinger_bands(prices, period=20)
        assert result is not None
        middle, upper, lower = result
        # With no variance, all bands equal the mean
        assert middle == 100.0
        assert upper == 100.0
        assert lower == 100.0

    def test_custom_std_dev(self) -> None:
        prices = [100.0 + i for i in range(20)]
        result_2std = calculate_bollinger_bands(prices, period=20, num_std=2.0)
        result_1std = calculate_bollinger_bands(prices, period=20, num_std=1.0)

        assert result_2std is not None and result_1std is not None
        _, upper_2, lower_2 = result_2std
        _, upper_1, lower_1 = result_1std

        # 2 std bands should be wider than 1 std bands
        assert (upper_2 - lower_2) > (upper_1 - lower_1)

    def test_bands_symmetry(self) -> None:
        prices = [100.0 + i for i in range(20)]
        result = calculate_bollinger_bands(prices, period=20)
        assert result is not None
        middle, upper, lower = result
        # Upper and lower should be equidistant from middle
        assert (upper - middle) == pytest.approx(middle - lower, rel=0.001)


class TestCalculateBollingerBandwidth:
    """Tests for calculate_bollinger_bandwidth function."""

    def test_insufficient_data(self) -> None:
        prices = [100.0, 101.0]
        result = calculate_bollinger_bandwidth(prices, period=20)
        assert result is None

    def test_constant_prices(self) -> None:
        prices = [100.0] * 25
        result = calculate_bollinger_bandwidth(prices, period=20)
        assert result is not None
        assert result == 0.0  # No bandwidth when no variance

    def test_bandwidth_increases_with_volatility(self) -> None:
        # Low volatility
        low_vol = [100.0 + (i % 2) for i in range(25)]
        # High volatility
        high_vol = [100.0 + (i % 2) * 10 for i in range(25)]

        bw_low = calculate_bollinger_bandwidth(low_vol, period=20)
        bw_high = calculate_bollinger_bandwidth(high_vol, period=20)

        assert bw_low is not None and bw_high is not None
        assert bw_high > bw_low


class TestCalculatePercentB:
    """Tests for calculate_percent_b function."""

    def test_insufficient_data(self) -> None:
        prices = [100.0, 101.0]
        result = calculate_percent_b(prices, period=20)
        assert result is None

    def test_empty_prices(self) -> None:
        result = calculate_percent_b([], period=20)
        assert result is None

    def test_price_at_lower_band(self) -> None:
        # Create prices where current price is at lower band
        prices = [100.0] * 19 + [90.0]  # Drop to lower band
        result = calculate_percent_b(prices, period=20)
        # %B should be around 0 (at lower band)
        assert result is not None
        assert result < 0.3

    def test_price_at_upper_band(self) -> None:
        # Create prices where current price is at upper band
        prices = [100.0] * 19 + [110.0]  # Jump to upper band
        result = calculate_percent_b(prices, period=20)
        # %B should be around 1 (at upper band)
        assert result is not None
        assert result > 0.7

    def test_price_at_middle(self) -> None:
        # Constant prices = price at middle band
        prices = [100.0] * 25
        result = calculate_percent_b(prices, period=20)
        # With no variance, bands collapse to middle, cannot calculate %B
        assert result is None  # Division by zero case

    def test_trending_prices(self) -> None:
        prices = [100.0 + i for i in range(25)]
        result = calculate_percent_b(prices, period=20)
        assert result is not None
        # In uptrend, price should be above middle, so %B > 0.5
        assert result > 0.5
