"""Unit tests for technical indicators."""

import pytest

from axtrade.indicators import IndicatorEngine, calculate_rsi, calculate_sma


class TestCalculateSMA:
    """Tests for SMA calculation."""

    def test_exact_period(self) -> None:
        prices = [10.0, 11.0, 12.0, 13.0, 14.0]
        result = calculate_sma(prices, 5)
        assert result == 12.0

    def test_more_than_period(self) -> None:
        prices = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        # Should use last 5: [3, 4, 5, 6, 7] = 25/5 = 5.0
        result = calculate_sma(prices, 5)
        assert result == 5.0

    def test_less_than_period(self) -> None:
        prices = [10.0, 11.0, 12.0]
        result = calculate_sma(prices, 5)
        assert result is None

    def test_single_price_period_one(self) -> None:
        prices = [100.0]
        result = calculate_sma(prices, 1)
        assert result == 100.0

    def test_empty_prices(self) -> None:
        result = calculate_sma([], 5)
        assert result is None


class TestCalculateRSI:
    """Tests for RSI calculation."""

    def test_uptrend_high_rsi(self) -> None:
        # Consistent uptrend should have RSI near 100
        prices = [100.0 + i for i in range(20)]
        result = calculate_rsi(prices, 14)
        assert result is not None
        assert result > 90

    def test_downtrend_low_rsi(self) -> None:
        # Consistent downtrend should have RSI near 0
        prices = [100.0 - i for i in range(20)]
        result = calculate_rsi(prices, 14)
        assert result is not None
        assert result < 10

    def test_flat_prices(self) -> None:
        # Flat prices should have RSI undefined or 50-ish
        prices = [100.0] * 20
        result = calculate_rsi(prices, 14)
        # With zero loss, RSI should be 100
        assert result == 100.0

    def test_insufficient_data(self) -> None:
        # Need period + 1 prices (15 for RSI-14)
        prices = [100.0 + i for i in range(10)]
        result = calculate_rsi(prices, 14)
        assert result is None

    def test_exact_minimum_data(self) -> None:
        # Exactly 15 prices for RSI-14
        prices = [100.0 + i * 0.5 for i in range(15)]
        result = calculate_rsi(prices, 14)
        assert result is not None

    def test_alternating_prices(self) -> None:
        # Alternating up/down should be around 50
        prices = []
        for i in range(20):
            prices.append(100.0 + (1 if i % 2 == 0 else -1))
        result = calculate_rsi(prices, 14)
        assert result is not None
        assert 40 < result < 60


class TestIndicatorEngine:
    """Tests for IndicatorEngine."""

    def test_process_bar_without_warmup(self) -> None:
        engine = IndicatorEngine(sma_period=5, rsi_period=5)
        result = engine.process_bar("AAPL", "1m", 100.0)
        assert result.sma_20 is None
        assert result.rsi_14 is None

    def test_process_bar_enough_data_for_sma(self) -> None:
        engine = IndicatorEngine(sma_period=5, rsi_period=14)

        # Add 5 prices
        for i in range(5):
            result = engine.process_bar("AAPL", "1m", 100.0 + i)

        # 5th bar should have SMA but not RSI
        assert result.sma_20 is not None
        assert result.rsi_14 is None

    def test_process_bar_enough_data_for_rsi(self) -> None:
        engine = IndicatorEngine(sma_period=5, rsi_period=5)

        # Add 6 prices (need period + 1 for RSI)
        for i in range(6):
            result = engine.process_bar("AAPL", "1m", 100.0 + i)

        # Should have both SMA and RSI
        assert result.sma_20 is not None
        assert result.rsi_14 is not None

    def test_separate_buffers_per_symbol(self) -> None:
        engine = IndicatorEngine(sma_period=3, rsi_period=3)

        for i in range(5):
            engine.process_bar("AAPL", "1m", 100.0 + i)
            engine.process_bar("MSFT", "1m", 200.0 + i * 2)

        aapl_result = engine.process_bar("AAPL", "1m", 105.0)
        msft_result = engine.process_bar("MSFT", "1m", 210.0)

        # Both should have values but different
        assert aapl_result.sma_20 is not None
        assert msft_result.sma_20 is not None
        assert aapl_result.sma_20 != msft_result.sma_20

    def test_separate_buffers_per_interval(self) -> None:
        engine = IndicatorEngine(sma_period=3, rsi_period=3)

        for i in range(5):
            engine.process_bar("AAPL", "1m", 100.0 + i)

        # 5m should not have data yet
        assert engine.get_buffer_size("AAPL", "1m") == 5
        assert engine.get_buffer_size("AAPL", "5m") == 0

    def test_initialize_buffer(self) -> None:
        engine = IndicatorEngine(sma_period=5, rsi_period=5)

        # Initialize with historical data
        historical = [100.0, 101.0, 102.0, 103.0, 104.0]
        engine.initialize_buffer("AAPL", "1m", historical)

        # First new bar should already have SMA
        result = engine.process_bar("AAPL", "1m", 105.0)
        assert result.sma_20 is not None

    def test_buffer_rolls_over(self) -> None:
        engine = IndicatorEngine(sma_period=3, rsi_period=3)

        # Add more prices than buffer size
        for i in range(50):
            engine.process_bar("AAPL", "1m", 100.0 + i)

        # Buffer should be capped
        assert engine.get_buffer_size("AAPL", "1m") <= engine._buffer_size
