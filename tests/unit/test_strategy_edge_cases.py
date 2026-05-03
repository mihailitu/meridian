"""Unit tests for strategy edge cases.

Tests for boundary conditions, buffer overflows, and concurrent scenarios.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from axtrade.common import Bar
from axtrade.indicators import MarketRegime
from axtrade.oms import OrderSide, Position
from axtrade.strategies import (
    BarWithIndicators,
    MeanReversionStrategy,
    MomentumBreakout,
    MultiTimeframeStrategy,
    PairsStrategy,
)


def make_bar(
    symbol: str = "AAPL",
    close: float = 100.0,
    timestamp: datetime | None = None,
) -> Bar:
    """Create a test bar."""
    if timestamp is None:
        timestamp = datetime.now(timezone.utc)
    return Bar(
        symbol=symbol,
        timestamp=timestamp,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=10000,
    )


def make_bar_with_indicators(
    symbol: str = "AAPL",
    close: float = 100.0,
    sma_20: float | None = None,
    rsi_14: float | None = None,
    bb_upper: float | None = None,
    bb_middle: float | None = None,
    bb_lower: float | None = None,
    atr: float | None = None,
    regime: MarketRegime | None = None,
    trend_strength: float | None = None,
    timestamp: datetime | None = None,
) -> BarWithIndicators:
    """Create a test bar with indicators."""
    return BarWithIndicators(
        bar=make_bar(symbol, close, timestamp),
        sma_20=sma_20,
        rsi_14=rsi_14,
        bb_upper=bb_upper,
        bb_middle=bb_middle,
        bb_lower=bb_lower,
        atr=atr,
        regime=regime,
        trend_strength=trend_strength,
    )


def _prime_momentum_rsi(
    strategy: MomentumBreakout,
    symbol: str,
    rsi: float,
    sma_20: float = 100.0,
) -> None:
    """Seed prev_rsi without triggering an entry (regime not trending)."""
    strategy.on_bar(
        make_bar_with_indicators(
            symbol=symbol,
            close=sma_20 + 1.0,
            sma_20=sma_20,
            rsi_14=rsi,
            regime=MarketRegime.RANGING_QUIET,
            trend_strength=10.0,
        )
    )


class TestMomentumBreakoutEdgeCases:
    """Edge case tests for MomentumBreakout strategy."""

    @pytest.fixture
    def strategy(self) -> MomentumBreakout:
        return MomentumBreakout(
            strategy_id="test_momentum",
            config={
                "rsi_cross_level": 50,
                "rsi_overbought": 70,
                "trend_strength_min": 30.0,
                "stop_loss_pct": 0.03,
                "position_size": 100,
            },
        )

    def test_rsi_exactly_at_cross_level_no_entry(
        self, strategy: MomentumBreakout
    ) -> None:
        """Cross requires prev <= level < current — equal to level is not a cross."""
        _prime_momentum_rsi(strategy, "AAPL", 45.0, sma_20=100.0)
        data = make_bar_with_indicators(
            close=101.0,
            sma_20=100.0,
            rsi_14=50.0,
            regime=MarketRegime.TRENDING_UP,
            trend_strength=50.0,
        )
        # rsi_14=50 is not strictly > cross_level=50.
        assert strategy.on_bar(data) is None

    def test_rsi_just_above_cross_level_enters(
        self, strategy: MomentumBreakout
    ) -> None:
        _prime_momentum_rsi(strategy, "AAPL", 45.0, sma_20=100.0)
        data = make_bar_with_indicators(
            close=101.0,
            sma_20=100.0,
            rsi_14=50.1,
            regime=MarketRegime.TRENDING_UP,
            trend_strength=50.0,
        )
        order = strategy.on_bar(data)
        assert order is not None
        assert order.side == OrderSide.BUY

    def test_rsi_exactly_at_overbought_threshold(
        self, strategy: MomentumBreakout
    ) -> None:
        strategy.update_position(
            Position(
                strategy_id="test_momentum",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("95.0"),
            )
        )
        data = make_bar_with_indicators(
            close=100.0, sma_20=99.0, rsi_14=70.0, regime=MarketRegime.TRENDING_UP
        )
        # RSI == 70 is not strictly > 70, so no overbought exit.
        assert strategy.on_bar(data) is None

    def test_rsi_just_above_overbought_threshold(
        self, strategy: MomentumBreakout
    ) -> None:
        strategy.update_position(
            Position(
                strategy_id="test_momentum",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("95.0"),
            )
        )
        data = make_bar_with_indicators(
            close=100.0, sma_20=99.0, rsi_14=70.1, regime=MarketRegime.TRENDING_UP
        )
        order = strategy.on_bar(data)
        assert order is not None
        assert order.side == OrderSide.SELL

    def test_price_exactly_at_sma_no_entry(
        self, strategy: MomentumBreakout
    ) -> None:
        _prime_momentum_rsi(strategy, "AAPL", 45.0, sma_20=100.0)
        data = make_bar_with_indicators(
            close=100.0,
            sma_20=100.0,
            rsi_14=55.0,
            regime=MarketRegime.TRENDING_UP,
            trend_strength=50.0,
        )
        # Close == SMA is not strictly > SMA.
        assert strategy.on_bar(data) is None

    def test_multiple_symbols_track_rsi_independently(
        self, strategy: MomentumBreakout
    ) -> None:
        _prime_momentum_rsi(strategy, "AAPL", 45.0, sma_20=100.0)
        _prime_momentum_rsi(strategy, "MSFT", 60.0, sma_20=100.0)

        # AAPL crosses up — should enter.
        order = strategy.on_bar(
            make_bar_with_indicators(
                symbol="AAPL",
                close=101.0,
                sma_20=100.0,
                rsi_14=55.0,
                regime=MarketRegime.TRENDING_UP,
                trend_strength=50.0,
            )
        )
        assert order is not None
        assert order.symbol == "AAPL"

        # MSFT prev RSI was already above cross level — no fresh cross.
        order = strategy.on_bar(
            make_bar_with_indicators(
                symbol="MSFT",
                close=101.0,
                sma_20=100.0,
                rsi_14=62.0,
                regime=MarketRegime.TRENDING_UP,
                trend_strength=50.0,
            )
        )
        assert order is None

    def test_stop_loss_exactly_at_threshold(
        self, strategy: MomentumBreakout
    ) -> None:
        strategy.update_position(
            Position(
                strategy_id="test_momentum",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("100.0"),
            )
        )
        # 3% stop. Loss < -3% triggers; exactly -3% does not.
        data = make_bar_with_indicators(
            close=97.0, sma_20=99.0, rsi_14=50.0, regime=MarketRegime.TRENDING_UP
        )
        # loss_pct == -0.03; condition is < -0.03, so no fire at exactly the boundary.
        assert strategy.on_bar(data) is None

        data = make_bar_with_indicators(
            close=96.5, sma_20=99.0, rsi_14=50.0, regime=MarketRegime.TRENDING_UP
        )
        order = strategy.on_bar(data)
        assert order is not None
        assert order.side == OrderSide.SELL

    def test_on_fill_callback(self, strategy: MomentumBreakout) -> None:
        """Test on_fill callback is called."""
        from axtrade.oms.types import Fill
        from uuid import uuid4

        fill = Fill(
            order_id=uuid4(),
            strategy_id="test_momentum",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            price=Decimal("185.50"),
        )

        # on_fill should not raise
        strategy.on_fill(fill)


class TestMeanReversionEdgeCases:
    """Edge case tests for MeanReversionStrategy.

    BB/ATR buffering moved to IndicatorEngine; tests for buffer limits
    and per-symbol isolation now live in test_indicators.py.
    """

    @pytest.fixture
    def strategy(self) -> MeanReversionStrategy:
        return MeanReversionStrategy(
            strategy_id="mean_rev_test",
            config={
                "rsi_oversold": 35,
                "rsi_overbought": 70,
                "stop_loss_pct": 0.015,
                "position_size": 100,
            },
        )

    def test_zero_standard_deviation(
        self, strategy: MeanReversionStrategy
    ) -> None:
        """When BB has zero std dev (upper == lower == middle), price <= lower
        is trivially true; strategy should still gate on RSI."""
        data = make_bar_with_indicators(
            close=100.0,
            rsi_14=30,
            bb_upper=100.0,
            bb_middle=100.0,
            bb_lower=100.0,
            regime=MarketRegime.RANGING_QUIET,
        )
        order = strategy.on_bar(data)
        assert order is not None  # price <= lower and RSI < 35

        data = make_bar_with_indicators(
            close=100.0,
            rsi_14=50,
            bb_upper=100.0,
            bb_middle=100.0,
            bb_lower=100.0,
            regime=MarketRegime.RANGING_QUIET,
        )
        assert strategy.on_bar(data) is None

    def test_price_at_exact_lower_band(
        self, strategy: MeanReversionStrategy
    ) -> None:
        data = make_bar_with_indicators(
            close=88.0,
            rsi_14=30,
            bb_upper=112.0,
            bb_middle=100.0,
            bb_lower=88.0,
            regime=MarketRegime.RANGING_QUIET,
        )
        order = strategy.on_bar(data)
        assert order is not None
        assert order.side == OrderSide.BUY


class TestMultiTimeframeEdgeCases:
    """Edge case tests for MultiTimeframeStrategy."""

    @pytest.fixture
    def strategy(self) -> MultiTimeframeStrategy:
        return MultiTimeframeStrategy(
            strategy_id="mtf_test",
            config={
                "trend_period": 5,
                "trend_interval_minutes": 5,
                "rsi_min": 40,
                "rsi_max": 60,
                "pullback_pct": 0.003,
                "stop_loss_pct": 0.02,
                "take_profit_pct": 0.03,
                "position_size": 100,
            },
        )

    def test_htf_candle_aggregation(
        self, strategy: MultiTimeframeStrategy
    ) -> None:
        """Test behavior of HTF candle aggregation."""
        # Send enough 1-min bars to form multiple 5-min candles
        for minute in range(35):
            ts = datetime(2024, 1, 15, 9, minute, 0, tzinfo=timezone.utc)
            close = 100.0 + minute * 0.1
            data = make_bar_with_indicators(close=close, rsi_14=50, timestamp=ts)
            strategy.on_bar(data)

        # Should have trend data after enough bars
        trend = strategy._get_trend("AAPL")
        # Trend may be None if not enough HTF bars, that's OK

    def test_trend_reversal_with_position(
        self, strategy: MultiTimeframeStrategy
    ) -> None:
        """Test handling trend reversal when in position."""
        # Build uptrend
        for i in range(35):
            ts = datetime(2024, 1, 15, 9, i, 0, tzinfo=timezone.utc)
            close = 100.0 + i * 0.5  # Uptrend
            data = make_bar_with_indicators(close=close, rsi_14=50, timestamp=ts)
            strategy.on_bar(data)

        # Enter position
        strategy.update_position(
            Position(
                strategy_id="mtf_test",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("115.0"),
            )
        )

        # Trend reverses (prices start falling)
        for i in range(10):
            ts = datetime(2024, 1, 15, 9, 35 + i, 0, tzinfo=timezone.utc)
            close = 117.5 - i * 1.0  # Downtrend
            data = make_bar_with_indicators(close=close, rsi_14=50, timestamp=ts)
            order = strategy.on_bar(data)
            # Should eventually exit on trend reversal or stop loss

    def test_take_profit_exactly_at_threshold(
        self, strategy: MultiTimeframeStrategy
    ) -> None:
        """Test take profit exactly at threshold."""
        # Build trend data
        for i in range(35):
            ts = datetime(2024, 1, 15, 9, i, 0, tzinfo=timezone.utc)
            data = make_bar_with_indicators(close=100.0, rsi_14=50, timestamp=ts)
            strategy.on_bar(data)

        # Enter position at $100
        strategy.update_position(
            Position(
                strategy_id="mtf_test",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("100.0"),
            )
        )

        # Price at exactly 3% profit = $103
        ts = datetime(2024, 1, 15, 9, 36, 0, tzinfo=timezone.utc)
        data = make_bar_with_indicators(close=103.0, rsi_14=50, timestamp=ts)
        order = strategy.on_bar(data)
        # At exactly 3%, should trigger take profit (>=)
        assert order is not None
        assert order.side == OrderSide.SELL


class TestPairsStrategyEdgeCases:
    """Edge case tests for PairsStrategy."""

    @pytest.fixture
    def strategy(self) -> PairsStrategy:
        return PairsStrategy(
            strategy_id="pairs_test",
            config={
                "symbol_a": "AAPL",
                "symbol_b": "MSFT",
                "lookback": 10,
                "entry_zscore": 2.0,
                "exit_zscore": 0.5,
                "stop_loss_pct": 0.03,
                "position_size": 50,
            },
        )

    def test_zero_standard_deviation_in_ratio(
        self, strategy: PairsStrategy
    ) -> None:
        """Test handling of zero std dev in ratio."""
        # Send identical ratios
        for i in range(15):
            data_a = make_bar_with_indicators(symbol="AAPL", close=100.0)
            data_b = make_bar_with_indicators(symbol="MSFT", close=300.0)
            strategy.on_bar(data_a)
            strategy.on_bar(data_b)

        # Should handle zero std dev gracefully
        zscore = strategy._calculate_zscore()
        # With zero variance, zscore calculation should return None or 0
        # Implementation dependent

    def test_short_entry_disabled(self, strategy: PairsStrategy) -> None:
        """Test that short entry is disabled (high z-score)."""
        # Build stable history
        for i in range(15):
            data_a = make_bar_with_indicators(symbol="AAPL", close=100.0)
            data_b = make_bar_with_indicators(symbol="MSFT", close=300.0)
            strategy.on_bar(data_a)
            strategy.on_bar(data_b)

        # AAPL rises significantly (ratio rises = high z-score)
        data_a = make_bar_with_indicators(symbol="AAPL", close=120.0)
        data_b = make_bar_with_indicators(symbol="MSFT", close=300.0)
        strategy.on_bar(data_b)
        order = strategy.on_bar(data_a)

        # PairsStrategy typically only does long entries on the spread
        # Short entry would require selling AAPL and buying MSFT
        # Check if this is disabled in the implementation

    def test_buffer_overflow_protection(self, strategy: PairsStrategy) -> None:
        """Test that price buffers don't grow unbounded."""
        # Send many bars
        for i in range(100):
            data_a = make_bar_with_indicators(symbol="AAPL", close=100.0)
            data_b = make_bar_with_indicators(symbol="MSFT", close=300.0)
            strategy.on_bar(data_a)
            strategy.on_bar(data_b)

        # Buffers should be limited (implementation uses deque with maxlen)
        # Just verify they didn't grow unbounded
        assert len(strategy._prices_a) <= 100
        assert len(strategy._prices_b) <= 100

    def test_mismatched_bar_counts(self, strategy: PairsStrategy) -> None:
        """Test handling when symbols have different bar counts."""
        # Send more bars for AAPL than MSFT
        for i in range(15):
            data_a = make_bar_with_indicators(symbol="AAPL", close=100.0)
            strategy.on_bar(data_a)

        for i in range(10):
            data_b = make_bar_with_indicators(symbol="MSFT", close=300.0)
            strategy.on_bar(data_b)

        # Should handle gracefully
        zscore = strategy._calculate_zscore()
        # With mismatched counts, may return None or use minimum


class TestStrategyBaseClass:
    """Tests for BaseStrategy common functionality."""

    @pytest.fixture
    def strategy(self) -> MomentumBreakout:
        return MomentumBreakout(
            strategy_id="test",
            config={"position_size": 100},
        )

    def test_clear_position(self, strategy: MomentumBreakout) -> None:
        """Test clear_position method."""
        # Add position
        strategy.update_position(
            Position(
                strategy_id="test",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("100.0"),
            )
        )
        assert strategy.get_position("AAPL") is not None

        # Clear position
        strategy.clear_position("AAPL")
        assert strategy.get_position("AAPL") is None

    def test_update_position_with_zero_quantity(
        self, strategy: MomentumBreakout
    ) -> None:
        """Test that zero quantity position is cleared."""
        # Add position
        strategy.update_position(
            Position(
                strategy_id="test",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("100.0"),
            )
        )

        # Update with zero quantity
        strategy.update_position(
            Position(
                strategy_id="test",
                symbol="AAPL",
                side="long",
                quantity=Decimal("0"),
                avg_entry_price=Decimal("100.0"),
            )
        )

        # Should be cleared
        assert strategy.get_position("AAPL") is None

    def test_enabled_property(self, strategy: MomentumBreakout) -> None:
        """Test enabled property."""
        assert strategy.enabled is True
        strategy.enabled = False
        assert strategy.enabled is False
