"""Unit tests for trading strategies."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from axtrade.common import Bar
from axtrade.indicators import MarketRegime
from axtrade.oms import Order, OrderSide, Position
from axtrade.strategies import BarWithIndicators, MomentumBreakout


class TestBarWithIndicators:
    """Tests for BarWithIndicators."""

    def test_properties(self) -> None:
        bar = Bar(
            symbol="AAPL",
            open=185.0,
            high=186.0,
            low=184.0,
            close=185.5,
            volume=1000,
            timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
        )
        data = BarWithIndicators(bar=bar, sma_20=185.0, rsi_14=45.0)

        assert data.symbol == "AAPL"
        assert data.close == 185.5


class TestMomentumBreakout:
    """Tests for MomentumBreakout strategy."""

    @pytest.fixture
    def strategy(self) -> MomentumBreakout:
        return MomentumBreakout(
            strategy_id="test_momentum",
            config={
                "rsi_entry": 50,
                "rsi_overbought": 70,
                "stop_loss_pct": 0.03,
                "position_size": 100,
            },
        )

    @pytest.fixture
    def bar(self) -> Bar:
        return Bar(
            symbol="AAPL",
            open=185.0,
            high=186.0,
            low=184.0,
            close=185.5,
            volume=1000,
            timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
        )

    def test_name(self, strategy: MomentumBreakout) -> None:
        assert strategy.name == "MomentumBreakout"

    def test_no_signal_without_indicators(
        self, strategy: MomentumBreakout, bar: Bar
    ) -> None:
        """Should not generate signal without indicators."""
        data = BarWithIndicators(bar=bar, sma_20=None, rsi_14=None)
        order = strategy.on_bar(data)
        assert order is None

    def test_no_signal_missing_sma(
        self, strategy: MomentumBreakout, bar: Bar
    ) -> None:
        """Should not generate signal without SMA."""
        data = BarWithIndicators(bar=bar, sma_20=None, rsi_14=35.0)
        order = strategy.on_bar(data)
        assert order is None

    def test_no_signal_missing_rsi(
        self, strategy: MomentumBreakout, bar: Bar
    ) -> None:
        """Should not generate signal without RSI."""
        data = BarWithIndicators(bar=bar, sma_20=185.0, rsi_14=None)
        order = strategy.on_bar(data)
        assert order is None

    def test_buy_signal_rsi_crossover_with_regime(
        self, strategy: MomentumBreakout, bar: Bar
    ) -> None:
        """Should generate BUY when RSI crosses above 50 in TRENDING_UP regime."""
        # First bar: set prev RSI below 50
        data_prev = BarWithIndicators(
            bar=bar, sma_20=185.0, rsi_14=45.0,
            regime=MarketRegime.TRENDING_UP, trend_strength=50.0,
        )
        strategy.on_bar(data_prev)

        # Second bar: RSI crosses above 50
        data = BarWithIndicators(
            bar=bar, sma_20=185.0, rsi_14=52.0,
            regime=MarketRegime.TRENDING_UP, trend_strength=50.0,
        )
        order = strategy.on_bar(data)

        assert order is not None
        assert order.side == OrderSide.BUY
        assert order.symbol == "AAPL"
        assert order.quantity == Decimal("100")
        assert order.strategy_id == "test_momentum"

    def test_no_buy_signal_without_crossover(
        self, strategy: MomentumBreakout, bar: Bar
    ) -> None:
        """Should not generate BUY when RSI is already above entry level."""
        # Prev RSI already above 50
        data_prev = BarWithIndicators(
            bar=bar, sma_20=185.0, rsi_14=55.0,
            regime=MarketRegime.TRENDING_UP, trend_strength=50.0,
        )
        strategy.on_bar(data_prev)

        data = BarWithIndicators(
            bar=bar, sma_20=185.0, rsi_14=56.0,
            regime=MarketRegime.TRENDING_UP, trend_strength=50.0,
        )
        order = strategy.on_bar(data)
        assert order is None

    def test_no_buy_signal_price_below_sma(
        self, strategy: MomentumBreakout, bar: Bar
    ) -> None:
        """Should not generate BUY when price < SMA."""
        data_prev = BarWithIndicators(
            bar=bar, sma_20=186.0, rsi_14=45.0,
            regime=MarketRegime.TRENDING_UP, trend_strength=50.0,
        )
        strategy.on_bar(data_prev)

        data = BarWithIndicators(
            bar=bar, sma_20=186.0, rsi_14=52.0,
            regime=MarketRegime.TRENDING_UP, trend_strength=50.0,
        )
        order = strategy.on_bar(data)
        assert order is None

    def test_sell_signal_rsi_overbought(
        self, strategy: MomentumBreakout, bar: Bar
    ) -> None:
        """Should generate SELL when RSI > 70 with open position."""
        # Setup: strategy has an open position
        position = Position(
            strategy_id="test_momentum",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("180.0"),
        )
        strategy.update_position(position)

        # RSI (75) > 70
        data = BarWithIndicators(bar=bar, sma_20=185.0, rsi_14=75.0)
        order = strategy.on_bar(data)

        assert order is not None
        assert order.side == OrderSide.SELL
        assert order.quantity == Decimal("100")

    def test_sell_signal_regime_downtrend(
        self, strategy: MomentumBreakout, bar: Bar
    ) -> None:
        """Should generate SELL when regime shifts to TRENDING_DOWN."""
        position = Position(
            strategy_id="test_momentum",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("180.0"),
        )
        strategy.update_position(position)

        data = BarWithIndicators(
            bar=bar, sma_20=185.0, rsi_14=50.0,
            regime=MarketRegime.TRENDING_DOWN,
        )
        order = strategy.on_bar(data)

        assert order is not None
        assert order.side == OrderSide.SELL

    def test_sell_signal_stop_loss(self, strategy: MomentumBreakout) -> None:
        """Should generate SELL when stop loss is triggered (3%)."""
        position = Position(
            strategy_id="test_momentum",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("192.0"),  # Entry at 192
        )
        strategy.update_position(position)

        # Current price 185.5, loss = (185.5-192)/192 = -3.4% > 3% stop
        bar = Bar(
            symbol="AAPL",
            open=186.0,
            high=186.5,
            low=185.0,
            close=185.5,
            volume=1000,
            timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
        )
        data = BarWithIndicators(bar=bar, sma_20=187.0, rsi_14=50.0)
        order = strategy.on_bar(data)

        assert order is not None
        assert order.side == OrderSide.SELL

    def test_no_sell_without_position(
        self, strategy: MomentumBreakout, bar: Bar
    ) -> None:
        """Should not generate SELL without an open position."""
        # RSI overbought but no position
        data = BarWithIndicators(bar=bar, sma_20=185.0, rsi_14=75.0)
        order = strategy.on_bar(data)
        assert order is None

    def test_hold_with_position_normal_conditions(
        self, strategy: MomentumBreakout, bar: Bar
    ) -> None:
        """Should not generate signal in normal conditions with position."""
        position = Position(
            strategy_id="test_momentum",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("184.0"),  # In profit
        )
        strategy.update_position(position)

        # Price above SMA, RSI in normal range
        data = BarWithIndicators(bar=bar, sma_20=185.0, rsi_14=55.0)
        order = strategy.on_bar(data)
        assert order is None

    def test_position_management(self, strategy: MomentumBreakout) -> None:
        """Test position update and clear."""
        position = Position(
            strategy_id="test_momentum",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("185.0"),
        )

        # Update position
        strategy.update_position(position)
        assert strategy.get_position("AAPL") == position

        # Clear position (quantity = 0)
        position.quantity = Decimal("0")
        strategy.update_position(position)
        assert strategy.get_position("AAPL") is None

    def test_custom_config(self) -> None:
        """Test strategy with custom configuration."""
        strategy = MomentumBreakout(
            strategy_id="custom",
            config={
                "rsi_entry": 45,
                "rsi_overbought": 80,
                "min_trend_strength": 40,
                "stop_loss_pct": 0.05,
                "position_size": 50,
            },
        )

        assert strategy.rsi_entry == 45
        assert strategy.rsi_overbought == 80
        assert strategy.min_trend_strength == 40
        assert strategy.stop_loss_pct == 0.05
        assert strategy._fallback_position_size == Decimal("50")
