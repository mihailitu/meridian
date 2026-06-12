"""Tests for BuyHoldStrategy.

Verifies: one-buy-per-symbol semantics, allowed_symbols filtering,
no-filter default, max_positions capacity guard, and indicator-independence.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from axtrade.common import Bar
from axtrade.oms import Order, OrderSide, OrderType, Position
from axtrade.strategies import BarWithIndicators
from axtrade.strategies.buy_hold import BuyHoldStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _bar(symbol: str = "AAPL", close: float = 150.0) -> BarWithIndicators:
    ts = datetime(2025, 8, 1, 14, 0, tzinfo=timezone.utc)
    return BarWithIndicators(
        bar=Bar(
            symbol=symbol,
            timestamp=ts,
            open=close,
            high=close + 1,
            low=close - 1,
            close=close,
            volume=10_000,
        ),
        # All indicators left at their defaults (None)
    )


def _position(strategy_id: str, symbol: str) -> Position:
    return Position(
        strategy_id=strategy_id,
        symbol=symbol,
        side="long",
        quantity=Decimal("100"),
        avg_entry_price=Decimal("150"),
    )


# ---------------------------------------------------------------------------
# One-buy-per-symbol semantics
# ---------------------------------------------------------------------------

class TestOneBuyPerSymbol:
    def test_first_bar_returns_buy_order(self) -> None:
        strat = BuyHoldStrategy("bh_test", {"position_size": 50})
        order = strat.on_bar(_bar("AAPL"))
        assert order is not None
        assert isinstance(order, Order)
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.MARKET
        assert order.symbol == "AAPL"
        assert order.strategy_id == "bh_test"
        assert order.quantity == Decimal("50")

    def test_second_bar_same_symbol_returns_none(self) -> None:
        strat = BuyHoldStrategy("bh_test", {"position_size": 50})
        strat.on_bar(_bar("AAPL"))
        # Second bar for same symbol — no position recorded yet
        result = strat.on_bar(_bar("AAPL"))
        assert result is None

    def test_quantity_matches_position_size_config(self) -> None:
        strat = BuyHoldStrategy("bh_test", {"position_size": 123})
        order = strat.on_bar(_bar("AAPL"))
        assert order is not None
        assert order.quantity == Decimal("123")

    def test_default_position_size_is_100(self) -> None:
        strat = BuyHoldStrategy("bh_test", {})
        order = strat.on_bar(_bar("AAPL"))
        assert order is not None
        assert order.quantity == Decimal("100")


# ---------------------------------------------------------------------------
# allowed_symbols filtering
# ---------------------------------------------------------------------------

class TestAllowedSymbols:
    def test_allowed_symbol_returns_order(self) -> None:
        strat = BuyHoldStrategy("bh_test", {"allowed_symbols": ["AAPL", "MSFT"]})
        order = strat.on_bar(_bar("AAPL"))
        assert order is not None

    def test_blocked_symbol_returns_none(self) -> None:
        strat = BuyHoldStrategy("bh_test", {"allowed_symbols": ["AAPL"]})
        order = strat.on_bar(_bar("TSLA"))
        assert order is None

    def test_blocked_symbol_does_not_consume_capacity(self) -> None:
        strat = BuyHoldStrategy("bh_test", {"allowed_symbols": ["AAPL"], "max_positions": 2})
        # TSLA is outside the universe — should not affect capacity
        strat.on_bar(_bar("TSLA"))
        # TSLA must not appear in _ordered
        assert "TSLA" not in strat._ordered

    def test_no_allowed_symbols_any_symbol_gets_bought(self) -> None:
        strat = BuyHoldStrategy("bh_test", {})
        assert strat.allowed_symbols is None
        order = strat.on_bar(_bar("ZBH"))
        assert order is not None
        assert order.symbol == "ZBH"

    def test_empty_allowed_symbols_means_no_filter(self) -> None:
        # Falsy config value should keep allowed_symbols as None
        strat = BuyHoldStrategy("bh_test", {"allowed_symbols": []})
        assert strat.allowed_symbols is None
        order = strat.on_bar(_bar("NVDA"))
        assert order is not None


# ---------------------------------------------------------------------------
# max_positions / capacity guard
# ---------------------------------------------------------------------------

class TestCapacity:
    def test_at_capacity_blocks_new_symbol(self) -> None:
        strat = BuyHoldStrategy("bh_test", {"max_positions": 1})
        # Record a position so the strategy is at capacity
        strat.update_position(_position("bh_test", "AAPL"))
        # A different symbol's first bar should be blocked
        order = strat.on_bar(_bar("MSFT"))
        assert order is None

    def test_capacity_allows_first_position(self) -> None:
        strat = BuyHoldStrategy("bh_test", {"max_positions": 1})
        order = strat.on_bar(_bar("AAPL"))
        assert order is not None

    def test_no_max_positions_never_blocks(self) -> None:
        strat = BuyHoldStrategy("bh_test", {})
        assert strat.max_positions is None
        # Buy several symbols — none should be blocked by capacity
        for sym in ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]:
            strat.update_position(_position("bh_test", sym))
        order = strat.on_bar(_bar("META"))
        assert order is not None


# ---------------------------------------------------------------------------
# Indicator independence
# ---------------------------------------------------------------------------

class TestIndicatorIndependence:
    def test_bar_with_no_indicators_still_produces_order(self) -> None:
        strat = BuyHoldStrategy("bh_test", {})
        # All indicator fields are None (default)
        bar = _bar("AAPL")
        assert bar.sma_20 is None
        assert bar.rsi_14 is None
        order = strat.on_bar(bar)
        assert order is not None
        assert order.symbol == "AAPL"
