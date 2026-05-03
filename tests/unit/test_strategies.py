"""Unit tests for trading strategies."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from axtrade.common import Bar
from axtrade.indicators import MarketRegime
from axtrade.oms import OrderSide, Position
from axtrade.strategies import BarWithIndicators, MomentumBreakout


def make_bar(
    symbol: str = "AAPL",
    close: float = 100.0,
    timestamp: datetime | None = None,
) -> Bar:
    if timestamp is None:
        timestamp = datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc)
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
    regime: MarketRegime | None = MarketRegime.TRENDING_UP,
    trend_strength: float | None = 50.0,
    timestamp: datetime | None = None,
) -> BarWithIndicators:
    return BarWithIndicators(
        bar=make_bar(symbol, close, timestamp),
        sma_20=sma_20,
        rsi_14=rsi_14,
        regime=regime,
        trend_strength=trend_strength,
    )


def prime_rsi(
    strategy: MomentumBreakout,
    symbol: str,
    rsi: float,
    *,
    sma_20: float = 100.0,
    close: float = 101.0,
    regime: MarketRegime = MarketRegime.RANGING_QUIET,
) -> None:
    """Send one bar so prev_rsi is populated for the symbol.

    Defaults to a non-triggering regime so this never produces an order.
    """
    strategy.on_bar(
        make_bar_with_indicators(
            symbol=symbol,
            close=close,
            sma_20=sma_20,
            rsi_14=rsi,
            regime=regime,
            trend_strength=10.0,
        )
    )


class TestBarWithIndicators:
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


class TestBaseStrategyMaxPositions:
    @staticmethod
    def _make_position(symbol: str) -> Position:
        return Position(
            strategy_id="test",
            symbol=symbol,
            side="long",
            quantity=Decimal(100),
            avg_entry_price=Decimal("100"),
        )

    def test_unlimited_when_unset(self) -> None:
        strat = MomentumBreakout("test", {})
        assert strat.max_positions is None
        for sym in ("AAPL", "MSFT", "GOOGL"):
            strat.update_position(self._make_position(sym))
        assert strat.at_capacity() is False

    def test_at_capacity_when_set(self) -> None:
        strat = MomentumBreakout("test", {"max_positions": 2})
        assert strat.max_positions == 2
        assert strat.at_capacity() is False
        strat.update_position(self._make_position("AAPL"))
        assert strat.at_capacity() is False
        strat.update_position(self._make_position("MSFT"))
        assert strat.at_capacity() is True
        strat.update_position(self._make_position("GOOGL"))
        assert strat.at_capacity() is True

    def test_at_capacity_clears_when_position_closed(self) -> None:
        strat = MomentumBreakout("test", {"max_positions": 1})
        strat.update_position(self._make_position("AAPL"))
        assert strat.at_capacity() is True
        strat.clear_position("AAPL")
        assert strat.at_capacity() is False


class TestMomentumBreakout:
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

    def test_name(self, strategy: MomentumBreakout) -> None:
        assert strategy.name == "MomentumBreakout"

    def test_no_signal_without_indicators(self, strategy: MomentumBreakout) -> None:
        data = make_bar_with_indicators(close=101.0, sma_20=None, rsi_14=None)
        assert strategy.on_bar(data) is None

    def test_no_signal_missing_sma(self, strategy: MomentumBreakout) -> None:
        data = make_bar_with_indicators(close=101.0, sma_20=None, rsi_14=55.0)
        assert strategy.on_bar(data) is None

    def test_no_signal_missing_rsi(self, strategy: MomentumBreakout) -> None:
        data = make_bar_with_indicators(close=101.0, sma_20=100.0, rsi_14=None)
        assert strategy.on_bar(data) is None

    def test_buy_signal_on_rsi_cross_in_trending_up(
        self, strategy: MomentumBreakout
    ) -> None:
        prime_rsi(strategy, "AAPL", rsi=45.0, sma_20=100.0)
        data = make_bar_with_indicators(
            close=101.0, sma_20=100.0, rsi_14=55.0, regime=MarketRegime.TRENDING_UP
        )
        order = strategy.on_bar(data)

        assert order is not None
        assert order.side == OrderSide.BUY
        assert order.symbol == "AAPL"
        assert order.quantity == Decimal("100")

    def test_buy_signal_on_breakout_regime(
        self, strategy: MomentumBreakout
    ) -> None:
        prime_rsi(strategy, "AAPL", rsi=48.0, sma_20=100.0)
        data = make_bar_with_indicators(
            close=101.0, sma_20=100.0, rsi_14=52.0, regime=MarketRegime.BREAKOUT
        )
        order = strategy.on_bar(data)
        assert order is not None
        assert order.side == OrderSide.BUY

    def test_no_buy_when_already_above_threshold(
        self, strategy: MomentumBreakout
    ) -> None:
        # Prev RSI already over the cross level → no fresh cross.
        prime_rsi(strategy, "AAPL", rsi=55.0, sma_20=100.0)
        data = make_bar_with_indicators(
            close=101.0, sma_20=100.0, rsi_14=58.0, regime=MarketRegime.TRENDING_UP
        )
        assert strategy.on_bar(data) is None

    def test_no_buy_when_regime_not_trending(
        self, strategy: MomentumBreakout
    ) -> None:
        prime_rsi(strategy, "AAPL", rsi=45.0, sma_20=100.0)
        data = make_bar_with_indicators(
            close=101.0,
            sma_20=100.0,
            rsi_14=55.0,
            regime=MarketRegime.RANGING_QUIET,
        )
        assert strategy.on_bar(data) is None

    def test_no_buy_when_trend_strength_below_min(
        self, strategy: MomentumBreakout
    ) -> None:
        prime_rsi(strategy, "AAPL", rsi=45.0, sma_20=100.0)
        data = make_bar_with_indicators(
            close=101.0,
            sma_20=100.0,
            rsi_14=55.0,
            regime=MarketRegime.TRENDING_UP,
            trend_strength=20.0,
        )
        assert strategy.on_bar(data) is None

    def test_no_buy_when_price_below_sma(self, strategy: MomentumBreakout) -> None:
        prime_rsi(strategy, "AAPL", rsi=45.0, sma_20=100.0)
        data = make_bar_with_indicators(
            close=99.0, sma_20=100.0, rsi_14=55.0, regime=MarketRegime.TRENDING_UP
        )
        assert strategy.on_bar(data) is None

    def test_no_buy_without_prev_rsi(self, strategy: MomentumBreakout) -> None:
        # Very first bar — no prior RSI to compare against.
        data = make_bar_with_indicators(
            close=101.0, sma_20=100.0, rsi_14=55.0, regime=MarketRegime.TRENDING_UP
        )
        assert strategy.on_bar(data) is None

    def test_at_capacity_blocks_entry(self) -> None:
        strategy = MomentumBreakout(
            strategy_id="cap",
            config={"max_positions": 1, "position_size": 100},
        )
        strategy.update_position(
            Position(
                strategy_id="cap",
                symbol="MSFT",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("100"),
            )
        )
        prime_rsi(strategy, "AAPL", rsi=45.0, sma_20=100.0)
        data = make_bar_with_indicators(
            close=101.0, sma_20=100.0, rsi_14=55.0, regime=MarketRegime.TRENDING_UP
        )
        assert strategy.on_bar(data) is None

    def test_sell_on_overbought_rsi(self, strategy: MomentumBreakout) -> None:
        strategy.update_position(
            Position(
                strategy_id="test_momentum",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("100.0"),
            )
        )
        data = make_bar_with_indicators(
            close=110.0, sma_20=105.0, rsi_14=75.0, regime=MarketRegime.TRENDING_UP
        )
        order = strategy.on_bar(data)
        assert order is not None
        assert order.side == OrderSide.SELL

    def test_sell_on_trending_down_regime(
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
        data = make_bar_with_indicators(
            close=99.5,
            sma_20=100.0,
            rsi_14=45.0,
            regime=MarketRegime.TRENDING_DOWN,
        )
        order = strategy.on_bar(data)
        assert order is not None
        assert order.side == OrderSide.SELL

    def test_sell_on_stop_loss(self, strategy: MomentumBreakout) -> None:
        strategy.update_position(
            Position(
                strategy_id="test_momentum",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("100.0"),
            )
        )
        # 3% stop, price down 4%
        data = make_bar_with_indicators(
            close=96.0, sma_20=100.0, rsi_14=45.0, regime=MarketRegime.TRENDING_UP
        )
        order = strategy.on_bar(data)
        assert order is not None
        assert order.side == OrderSide.SELL

    def test_no_sell_without_position(self, strategy: MomentumBreakout) -> None:
        prime_rsi(strategy, "AAPL", rsi=80.0)
        data = make_bar_with_indicators(
            close=101.0, sma_20=100.0, rsi_14=85.0, regime=MarketRegime.TRENDING_UP
        )
        # RSI overbought but no position → no exit, and no entry on this cross.
        assert strategy.on_bar(data) is None

    def test_hold_with_position_normal_conditions(
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
        data = make_bar_with_indicators(
            close=101.0, sma_20=100.0, rsi_14=55.0, regime=MarketRegime.TRENDING_UP
        )
        assert strategy.on_bar(data) is None

    def test_position_management(self, strategy: MomentumBreakout) -> None:
        position = Position(
            strategy_id="test_momentum",
            symbol="AAPL",
            side="long",
            quantity=Decimal("100"),
            avg_entry_price=Decimal("185.0"),
        )

        strategy.update_position(position)
        assert strategy.get_position("AAPL") == position

        position.quantity = Decimal("0")
        strategy.update_position(position)
        assert strategy.get_position("AAPL") is None

    def test_custom_config(self) -> None:
        strategy = MomentumBreakout(
            strategy_id="custom",
            config={
                "rsi_cross_level": 40,
                "rsi_overbought": 80,
                "trend_strength_min": 20.0,
                "stop_loss_pct": 0.05,
                "position_size": 50,
            },
        )

        assert strategy.rsi_cross_level == 40
        assert strategy.rsi_overbought == 80
        assert strategy.trend_strength_min == 20.0
        assert strategy.stop_loss_pct == 0.05
        assert strategy.position_size == Decimal("50")
