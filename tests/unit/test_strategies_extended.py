"""Unit tests for extended trading strategies."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from axtrade.common import Bar
from axtrade.indicators import MarketRegime
from axtrade.oms import OrderSide, Position
from axtrade.strategies import (
    BarWithIndicators,
    MeanReversionStrategy,
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
    regime: MarketRegime | None = MarketRegime.RANGING_QUIET,
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
    )


class TestMeanReversionStrategy:
    """Tests for MeanReversionStrategy."""

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

    def test_name(self, strategy: MeanReversionStrategy) -> None:
        assert strategy.name == "MeanReversion"

    def test_no_signal_without_bands(
        self, strategy: MeanReversionStrategy
    ) -> None:
        data = make_bar_with_indicators(close=100, rsi_14=30)
        assert strategy.on_bar(data) is None

    def test_buy_signal_at_lower_band_in_ranging_regime(
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
        assert order.quantity == Decimal("100")

    def test_no_buy_when_regime_trending_down(
        self, strategy: MeanReversionStrategy
    ) -> None:
        # Trending down was the historical worst-case for mean reversion;
        # the strategy must skip those bars even with a textbook setup.
        data = make_bar_with_indicators(
            close=88.0,
            rsi_14=30,
            bb_upper=112.0,
            bb_middle=100.0,
            bb_lower=88.0,
            regime=MarketRegime.TRENDING_DOWN,
        )
        assert strategy.on_bar(data) is None

    def test_no_buy_signal_without_rsi(
        self, strategy: MeanReversionStrategy
    ) -> None:
        data = make_bar_with_indicators(
            close=88.0,
            rsi_14=None,
            bb_upper=112.0,
            bb_middle=100.0,
            bb_lower=88.0,
            regime=MarketRegime.RANGING_QUIET,
        )
        assert strategy.on_bar(data) is None

    def test_sell_signal_at_upper_band(
        self, strategy: MeanReversionStrategy
    ) -> None:
        # Exit target is the upper band (full mean-reversion swing).
        strategy.update_position(
            Position(
                strategy_id="mean_rev_test",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("90.0"),
            )
        )

        data = make_bar_with_indicators(
            close=112.0,
            rsi_14=55,
            bb_upper=112.0,
            bb_middle=100.0,
            bb_lower=88.0,
            regime=MarketRegime.RANGING_QUIET,
        )
        order = strategy.on_bar(data)

        assert order is not None
        assert order.side == OrderSide.SELL

    def test_no_sell_below_upper_band(
        self, strategy: MeanReversionStrategy
    ) -> None:
        strategy.update_position(
            Position(
                strategy_id="mean_rev_test",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("90.0"),
            )
        )

        # Above middle but below upper band, RSI not overbought, no stop hit → hold.
        data = make_bar_with_indicators(
            close=105.0,
            rsi_14=55,
            bb_upper=112.0,
            bb_middle=100.0,
            bb_lower=88.0,
            regime=MarketRegime.RANGING_QUIET,
        )
        assert strategy.on_bar(data) is None

    def test_sell_signal_on_overbought_rsi(
        self, strategy: MeanReversionStrategy
    ) -> None:
        strategy.update_position(
            Position(
                strategy_id="mean_rev_test",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("95.0"),
            )
        )

        # RSI overbought trumps middle-band logic.
        data = make_bar_with_indicators(
            close=98.0,
            rsi_14=75,
            bb_upper=112.0,
            bb_middle=100.0,
            bb_lower=88.0,
            regime=MarketRegime.RANGING_QUIET,
        )
        order = strategy.on_bar(data)

        assert order is not None
        assert order.side == OrderSide.SELL

    def test_stop_loss_exit(self, strategy: MeanReversionStrategy) -> None:
        strategy.update_position(
            Position(
                strategy_id="mean_rev_test",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("100.0"),
            )
        )

        # 1.5% stop = $98.50; price at $98 triggers (loss > 1.5%).
        data = make_bar_with_indicators(
            close=98.0,
            rsi_14=40,
            bb_upper=112.0,
            bb_middle=100.0,
            bb_lower=88.0,
            regime=MarketRegime.RANGING_QUIET,
        )
        order = strategy.on_bar(data)

        assert order is not None
        assert order.side == OrderSide.SELL


class TestMultiTimeframeStrategy:
    """Tests for MultiTimeframeStrategy."""

    @pytest.fixture
    def strategy(self) -> MultiTimeframeStrategy:
        return MultiTimeframeStrategy(
            strategy_id="mtf_test",
            config={
                "trend_period": 5,  # Smaller for testing
                "trend_interval_minutes": 5,
                "rsi_min": 40,
                "rsi_max": 60,
                "pullback_pct": 0.003,
                "stop_loss_pct": 0.02,
                "take_profit_pct": 0.03,
                "position_size": 100,
            },
        )

    @staticmethod
    def _build_uptrend(strategy: MultiTimeframeStrategy) -> None:
        """Send 35 bars in an uptrend to populate the HTF trend buffer."""
        for i in range(35):
            ts = datetime(2024, 1, 15, 9, i, 0, tzinfo=timezone.utc)
            close = 100.0 + i * 0.5
            data = make_bar_with_indicators(close=close, rsi_14=50, timestamp=ts)
            strategy.on_bar(data)

    def test_name(self, strategy: MultiTimeframeStrategy) -> None:
        assert strategy.name == "MultiTimeframe"

    def test_no_signal_without_trend_data(
        self, strategy: MultiTimeframeStrategy
    ) -> None:
        for minute in range(3):
            ts = datetime(2024, 1, 15, 9, minute, 0, tzinfo=timezone.utc)
            data = make_bar_with_indicators(close=100.0, rsi_14=50, timestamp=ts)
            order = strategy.on_bar(data)
            assert order is None

    def test_builds_trend_data(self, strategy: MultiTimeframeStrategy) -> None:
        for i in range(30):
            ts = datetime(2024, 1, 15, 9, i, 0, tzinfo=timezone.utc)
            close = 100.0 + i * 0.1
            data = make_bar_with_indicators(close=close, rsi_14=50, timestamp=ts)
            strategy.on_bar(data)

        trend = strategy._get_trend("AAPL")
        assert trend is not None

    def test_buy_signal_on_pullback_to_sma(
        self, strategy: MultiTimeframeStrategy
    ) -> None:
        self._build_uptrend(strategy)

        # Pullback bar: close is right at SMA_20, RSI in neutral band, regime healthy.
        ts = datetime(2024, 1, 15, 9, 35, 0, tzinfo=timezone.utc)
        data = make_bar_with_indicators(
            close=117.5, sma_20=117.5, rsi_14=50, timestamp=ts
        )
        order = strategy.on_bar(data)

        assert order is not None
        assert order.side == OrderSide.BUY

    def test_no_buy_when_rsi_too_low(
        self, strategy: MultiTimeframeStrategy
    ) -> None:
        # Old "oversold" entry trap should NOT trigger anymore.
        self._build_uptrend(strategy)
        ts = datetime(2024, 1, 15, 9, 35, 0, tzinfo=timezone.utc)
        data = make_bar_with_indicators(
            close=117.5, sma_20=117.5, rsi_14=35, timestamp=ts
        )
        assert strategy.on_bar(data) is None

    def test_no_buy_when_price_too_far_from_sma(
        self, strategy: MultiTimeframeStrategy
    ) -> None:
        self._build_uptrend(strategy)
        ts = datetime(2024, 1, 15, 9, 35, 0, tzinfo=timezone.utc)
        # Price 1% above SMA — outside 0.3% pullback band.
        data = make_bar_with_indicators(
            close=120.0, sma_20=118.0, rsi_14=50, timestamp=ts
        )
        assert strategy.on_bar(data) is None

    def test_no_buy_when_regime_trending_down(
        self, strategy: MultiTimeframeStrategy
    ) -> None:
        from axtrade.indicators import MarketRegime
        self._build_uptrend(strategy)
        ts = datetime(2024, 1, 15, 9, 35, 0, tzinfo=timezone.utc)
        data = make_bar_with_indicators(
            close=117.5, sma_20=117.5, rsi_14=50, timestamp=ts
        )
        data.regime = MarketRegime.TRENDING_DOWN
        assert strategy.on_bar(data) is None

    def test_take_profit_exit(self, strategy: MultiTimeframeStrategy) -> None:
        self._build_uptrend(strategy)

        strategy.update_position(
            Position(
                strategy_id="mtf_test",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("100.0"),
            )
        )

        # Price up 3.5% — take profit (>= 3%).
        ts = datetime(2024, 1, 15, 9, 36, 0, tzinfo=timezone.utc)
        data = make_bar_with_indicators(close=103.5, rsi_14=50, timestamp=ts)
        order = strategy.on_bar(data)

        assert order is not None
        assert order.side == OrderSide.SELL

    def test_stop_loss_exit(self, strategy: MultiTimeframeStrategy) -> None:
        self._build_uptrend(strategy)

        strategy.update_position(
            Position(
                strategy_id="mtf_test",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("100.0"),
            )
        )

        # Price down 2.5% — stop loss (<= -2%).
        ts = datetime(2024, 1, 15, 9, 36, 0, tzinfo=timezone.utc)
        data = make_bar_with_indicators(close=97.5, rsi_14=50, timestamp=ts)
        order = strategy.on_bar(data)

        assert order is not None
        assert order.side == OrderSide.SELL


class TestPairsStrategy:
    """Tests for PairsStrategy."""

    @pytest.fixture
    def strategy(self) -> PairsStrategy:
        return PairsStrategy(
            strategy_id="pairs_test",
            config={
                "symbol_a": "AAPL",
                "symbol_b": "MSFT",
                "lookback": 10,  # Smaller for testing
                "entry_zscore": 2.0,
                "exit_zscore": 0.5,
                "stop_loss_pct": 0.03,
                "position_size": 50,
            },
        )

    def test_name(self, strategy: PairsStrategy) -> None:
        assert strategy.name == "Pairs(AAPL/MSFT)"

    def test_no_signal_without_enough_data(
        self, strategy: PairsStrategy
    ) -> None:
        # Only a few bars
        for i in range(5):
            data_a = make_bar_with_indicators(symbol="AAPL", close=100.0)
            data_b = make_bar_with_indicators(symbol="MSFT", close=300.0)
            strategy.on_bar(data_a)
            order = strategy.on_bar(data_b)
            assert order is None

    def test_builds_price_history(self, strategy: PairsStrategy) -> None:
        # Build history for both symbols
        for i in range(15):
            data_a = make_bar_with_indicators(symbol="AAPL", close=100.0 + i)
            data_b = make_bar_with_indicators(symbol="MSFT", close=300.0 + i)
            strategy.on_bar(data_a)
            strategy.on_bar(data_b)

        assert len(strategy._prices_a) == 15
        assert len(strategy._prices_b) == 15

    def test_zscore_calculation(self, strategy: PairsStrategy) -> None:
        # Build ratio history with variance in the ratio
        for i in range(15):
            # Add variance to AAPL only to create ratio variance
            noise = (i % 3) - 1  # -1, 0, 1 pattern
            data_a = make_bar_with_indicators(symbol="AAPL", close=100.0 + noise * 2)
            data_b = make_bar_with_indicators(symbol="MSFT", close=300.0)
            strategy.on_bar(data_a)
            strategy.on_bar(data_b)

        zscore = strategy._calculate_zscore()
        assert zscore is not None
        # Final ratio should be near mean, so z-score should be small
        assert abs(zscore) < 2.0

    def test_long_entry_on_low_zscore(self, strategy: PairsStrategy) -> None:
        # Build stable ratio history (AAPL:MSFT = 1:3)
        for i in range(15):
            data_a = make_bar_with_indicators(symbol="AAPL", close=100.0)
            data_b = make_bar_with_indicators(symbol="MSFT", close=300.0)
            strategy.on_bar(data_a)
            strategy.on_bar(data_b)

        # Now AAPL drops significantly (ratio falls)
        data_a = make_bar_with_indicators(symbol="AAPL", close=80.0)
        data_b = make_bar_with_indicators(symbol="MSFT", close=300.0)
        strategy.on_bar(data_b)
        order = strategy.on_bar(data_a)

        # Should trigger long entry (buy AAPL expecting ratio to recover)
        assert order is not None
        assert order.side == OrderSide.BUY
        assert order.symbol == "AAPL"
        assert strategy._spread_direction == "long"

    def test_exit_on_zscore_normalization(
        self, strategy: PairsStrategy
    ) -> None:
        # Build history with variance in ratio
        for i in range(15):
            noise = (i % 3) - 1
            data_a = make_bar_with_indicators(symbol="AAPL", close=100.0 + noise * 2)
            data_b = make_bar_with_indicators(symbol="MSFT", close=300.0)
            strategy.on_bar(data_a)
            strategy.on_bar(data_b)

        # Simulate being in long spread position
        strategy._spread_direction = "long"
        strategy.update_position(
            Position(
                strategy_id="pairs_test",
                symbol="AAPL",
                side="long",
                quantity=Decimal("50"),
                avg_entry_price=Decimal("80.0"),
            )
        )

        # Ratio normalizes (price at normal level, z-score should be small)
        data_a = make_bar_with_indicators(symbol="AAPL", close=100.0)
        data_b = make_bar_with_indicators(symbol="MSFT", close=300.0)
        strategy.on_bar(data_b)
        order = strategy.on_bar(data_a)

        assert order is not None
        assert order.side == OrderSide.SELL
        assert strategy._spread_direction is None

    def test_ignores_non_pair_symbols(self, strategy: PairsStrategy) -> None:
        # Build some history
        for i in range(15):
            data_a = make_bar_with_indicators(symbol="AAPL", close=100.0)
            data_b = make_bar_with_indicators(symbol="MSFT", close=300.0)
            strategy.on_bar(data_a)
            strategy.on_bar(data_b)

        # Random symbol should be ignored
        data_c = make_bar_with_indicators(symbol="GOOGL", close=150.0)
        order = strategy.on_bar(data_c)
        assert order is None

    def test_stop_loss_exit(self, strategy: PairsStrategy) -> None:
        # Build history
        for i in range(15):
            data_a = make_bar_with_indicators(symbol="AAPL", close=100.0)
            data_b = make_bar_with_indicators(symbol="MSFT", close=300.0)
            strategy.on_bar(data_a)
            strategy.on_bar(data_b)

        # Enter position
        strategy._spread_direction = "long"
        strategy.update_position(
            Position(
                strategy_id="pairs_test",
                symbol="AAPL",
                side="long",
                quantity=Decimal("50"),
                avg_entry_price=Decimal("100.0"),
            )
        )

        # Price drops below stop loss (3% = $97)
        data_a = make_bar_with_indicators(symbol="AAPL", close=96.0)
        data_b = make_bar_with_indicators(symbol="MSFT", close=300.0)
        strategy.on_bar(data_b)
        order = strategy.on_bar(data_a)

        assert order is not None
        assert order.side == OrderSide.SELL
