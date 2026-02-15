"""Tests for DiscoveryMomentumStrategy."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from axtrade.common import Bar
from axtrade.discovery.types import DiscoveredSymbol
from axtrade.oms import Order, OrderSide, Position
from axtrade.strategies.base import BarWithIndicators
from axtrade.strategies.discovery_momentum import DiscoveryMomentumStrategy


def make_bar_data(symbol="TSLA", close=250.0, sma=240.0, rsi=50.0):
    """Create a BarWithIndicators for testing."""
    bar = Bar(
        symbol=symbol,
        open=close - 1,
        high=close + 2,
        low=close - 2,
        close=close,
        volume=10000,
        timestamp=datetime.now(UTC),
        interval="1m",
    )
    return BarWithIndicators(bar=bar, sma_20=sma, rsi_14=rsi)


def make_discovery_service(symbols_with_scores=None):
    """Create a mock DiscoveryService."""
    svc = MagicMock()
    discovered = []
    if symbols_with_scores:
        for sym, score in symbols_with_scores:
            discovered.append(
                DiscoveredSymbol(symbol=sym, source="test", score=score)
            )
    svc.get_discovered.return_value = discovered
    return svc


class TestDiscoveryMomentumStrategy:
    """Tests for entry and exit logic."""

    @pytest.fixture
    def strategy(self):
        return DiscoveryMomentumStrategy(
            strategy_id="disc_mom_01",
            config={
                "min_score": 60,
                "position_size": 50,
                "stop_loss_pct": 0.03,
                "score_decay_exit": 30,
                "max_positions": 3,
            },
        )

    def test_returns_none_without_discovery_service(self, strategy):
        data = make_bar_data()
        result = strategy.on_bar(data)
        assert result is None

    def test_returns_none_without_indicators(self, strategy):
        svc = make_discovery_service([("TSLA", 80.0)])
        strategy.set_discovery_service(svc)

        bar = Bar(
            symbol="TSLA", open=249, high=252, low=248, close=250,
            volume=10000, timestamp=datetime.now(UTC), interval="1m",
        )
        data = BarWithIndicators(bar=bar, sma_20=None, rsi_14=None)
        result = strategy.on_bar(data)
        assert result is None

    def test_returns_none_when_symbol_not_discovered(self, strategy):
        svc = make_discovery_service([("AAPL", 80.0)])
        strategy.set_discovery_service(svc)

        data = make_bar_data(symbol="TSLA", close=250, sma=240, rsi=50)
        result = strategy.on_bar(data)
        assert result is None

    def test_buy_when_score_high_and_indicators_favorable(self, strategy):
        svc = make_discovery_service([("TSLA", 80.0)])
        strategy.set_discovery_service(svc)

        data = make_bar_data(symbol="TSLA", close=250, sma=240, rsi=50)
        order = strategy.on_bar(data)

        assert order is not None
        assert order.side == OrderSide.BUY
        assert order.symbol == "TSLA"
        assert order.quantity == Decimal("50")

    def test_no_buy_when_score_below_threshold(self, strategy):
        svc = make_discovery_service([("TSLA", 40.0)])
        strategy.set_discovery_service(svc)

        data = make_bar_data(symbol="TSLA", close=250, sma=240, rsi=50)
        assert strategy.on_bar(data) is None

    def test_no_buy_when_rsi_overbought(self, strategy):
        svc = make_discovery_service([("TSLA", 80.0)])
        strategy.set_discovery_service(svc)

        data = make_bar_data(symbol="TSLA", close=250, sma=240, rsi=75)
        assert strategy.on_bar(data) is None

    def test_no_buy_when_price_below_sma(self, strategy):
        svc = make_discovery_service([("TSLA", 80.0)])
        strategy.set_discovery_service(svc)

        data = make_bar_data(symbol="TSLA", close=230, sma=240, rsi=50)
        assert strategy.on_bar(data) is None

    def test_no_buy_when_max_positions_reached(self, strategy):
        svc = make_discovery_service([("TSLA", 80.0), ("META", 80.0), ("GOOG", 80.0), ("NFLX", 80.0)])
        strategy.set_discovery_service(svc)

        # Fill up positions
        for sym in ["A", "B", "C"]:
            strategy.positions[sym] = Position(
                strategy_id="disc_mom_01", symbol=sym, side="long",
                quantity=Decimal("50"), avg_entry_price=Decimal("100"),
            )

        data = make_bar_data(symbol="TSLA", close=250, sma=240, rsi=50)
        assert strategy.on_bar(data) is None

    def test_sell_on_score_decay(self, strategy):
        svc = make_discovery_service([("TSLA", 20.0)])  # Below score_decay_exit of 30
        strategy.set_discovery_service(svc)

        strategy.positions["TSLA"] = Position(
            strategy_id="disc_mom_01", symbol="TSLA", side="long",
            quantity=Decimal("50"), avg_entry_price=Decimal("240"),
        )

        data = make_bar_data(symbol="TSLA", close=250, sma=240, rsi=50)
        order = strategy.on_bar(data)

        assert order is not None
        assert order.side == OrderSide.SELL
        assert order.quantity == Decimal("50")

    def test_sell_when_symbol_removed_from_cache(self, strategy):
        svc = make_discovery_service([])  # TSLA not in discovered
        strategy.set_discovery_service(svc)

        strategy.positions["TSLA"] = Position(
            strategy_id="disc_mom_01", symbol="TSLA", side="long",
            quantity=Decimal("50"), avg_entry_price=Decimal("240"),
        )

        data = make_bar_data(symbol="TSLA", close=250, sma=240, rsi=50)
        order = strategy.on_bar(data)

        assert order is not None
        assert order.side == OrderSide.SELL

    def test_sell_on_stop_loss(self, strategy):
        svc = make_discovery_service([("TSLA", 80.0)])
        strategy.set_discovery_service(svc)

        strategy.positions["TSLA"] = Position(
            strategy_id="disc_mom_01", symbol="TSLA", side="long",
            quantity=Decimal("50"), avg_entry_price=Decimal("260"),
        )

        # Price dropped more than 3% below entry (260 -> 250 = -3.8%)
        data = make_bar_data(symbol="TSLA", close=250, sma=240, rsi=50)
        order = strategy.on_bar(data)

        assert order is not None
        assert order.side == OrderSide.SELL

    def test_sell_on_rsi_overbought(self, strategy):
        svc = make_discovery_service([("TSLA", 80.0)])
        strategy.set_discovery_service(svc)

        strategy.positions["TSLA"] = Position(
            strategy_id="disc_mom_01", symbol="TSLA", side="long",
            quantity=Decimal("50"), avg_entry_price=Decimal("240"),
        )

        data = make_bar_data(symbol="TSLA", close=260, sma=240, rsi=75)
        order = strategy.on_bar(data)

        assert order is not None
        assert order.side == OrderSide.SELL

    def test_hold_when_conditions_favorable(self, strategy):
        svc = make_discovery_service([("TSLA", 80.0)])
        strategy.set_discovery_service(svc)

        strategy.positions["TSLA"] = Position(
            strategy_id="disc_mom_01", symbol="TSLA", side="long",
            quantity=Decimal("50"), avg_entry_price=Decimal("245"),
        )

        data = make_bar_data(symbol="TSLA", close=250, sma=240, rsi=55)
        assert strategy.on_bar(data) is None

    def test_bearish_score_not_used_for_entry(self, strategy):
        svc = make_discovery_service([])
        # Add a bearish symbol manually (negative score)
        svc.get_discovered.return_value = [
            DiscoveredSymbol(symbol="TSLA", source="test", score=-80.0)
        ]
        strategy.set_discovery_service(svc)

        data = make_bar_data(symbol="TSLA", close=250, sma=240, rsi=50)
        assert strategy.on_bar(data) is None
