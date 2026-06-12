"""Tests for OvernightReversalStrategy.

Coverage:
 1. Entry happy path (EDT / August 2025)
 2. No entry when intraday drop is insufficient
 3. No entry outside the entry window
 4. Behavior when a session-open bar was never seen before the entry window
 5. One entry per symbol per day
 6. Exit at next session open
 7. EST equivalence (January 2026) and DST boundary
 8. allowed_symbols filtering
 9. Capacity guard
10. Exit with lost _entered_on state (fallback via position.opened_at)
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from axtrade.common import Bar
from axtrade.oms import Order, OrderSide, OrderType, Position
from axtrade.strategies import BarWithIndicators
from axtrade.strategies.overnight_reversal import OvernightReversalStrategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UTC = timezone.utc


def _bar(
    symbol: str,
    ts: datetime,
    open_price: float,
    close_price: float,
) -> BarWithIndicators:
    """Build a minimal BarWithIndicators; all indicator fields stay None."""
    return BarWithIndicators(
        bar=Bar(
            symbol=symbol,
            timestamp=ts,
            open=open_price,
            high=max(open_price, close_price) + 0.5,
            low=min(open_price, close_price) - 0.5,
            close=close_price,
            volume=10_000,
        )
    )


def _position(
    strategy_id: str,
    symbol: str,
    quantity: Decimal,
    opened_at: datetime,
) -> Position:
    return Position(
        strategy_id=strategy_id,
        symbol=symbol,
        side="long",
        quantity=quantity,
        avg_entry_price=Decimal("100"),
        opened_at=opened_at,
    )


def _strat(config: dict | None = None) -> OvernightReversalStrategy:
    cfg = config or {}
    return OvernightReversalStrategy("or_test", cfg)


# ---------------------------------------------------------------------------
# Test 1: Entry happy path (EDT, August 2025)
#   09:30 ET = 13:30 UTC  (EDT = UTC-4)
#   15:51 ET = 19:51 UTC
# ---------------------------------------------------------------------------

class TestEntryHappyPathEDT:
    def test_buy_order_on_qualifying_drop_in_window(self) -> None:
        strat = _strat({"position_size": 41, "loss_threshold_pct": 1.0})

        # Session-open bar: 13:30 UTC = 09:30 EDT on Aug 4, 2025
        ts_open = datetime(2025, 8, 4, 13, 30, tzinfo=_UTC)
        strat.on_bar(_bar("AAPL", ts_open, open_price=100.0, close_price=100.0))

        # Entry-window bar: 19:51 UTC = 15:51 EDT — qualifies (drop > 1%)
        ts_entry = datetime(2025, 8, 4, 19, 51, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_entry, open_price=100.0, close_price=98.5))

        assert order is not None
        assert isinstance(order, Order)
        assert order.side == OrderSide.BUY
        assert order.order_type == OrderType.MARKET
        assert order.symbol == "AAPL"
        assert order.strategy_id == "or_test"
        assert order.quantity == Decimal("41")

    def test_order_quantity_matches_config(self) -> None:
        strat = _strat({"position_size": 200})

        ts_open = datetime(2025, 8, 4, 13, 30, tzinfo=_UTC)
        strat.on_bar(_bar("AAPL", ts_open, 100.0, 100.0))

        ts_entry = datetime(2025, 8, 4, 19, 51, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_entry, 100.0, 98.0))

        assert order is not None
        assert order.quantity == Decimal("200")


# ---------------------------------------------------------------------------
# Test 2: No entry when drop is insufficient
# ---------------------------------------------------------------------------

class TestNoEntryInsufficientDrop:
    def test_drop_below_threshold_returns_none(self) -> None:
        strat = _strat({"loss_threshold_pct": 1.0})

        ts_open = datetime(2025, 8, 4, 13, 30, tzinfo=_UTC)
        strat.on_bar(_bar("AAPL", ts_open, 100.0, 100.0))

        # close=99.5 → only -0.5% drop, below the 1.0% threshold
        ts_entry = datetime(2025, 8, 4, 19, 51, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_entry, 100.0, 99.5))

        assert order is None

    def test_flat_close_returns_none(self) -> None:
        strat = _strat()

        ts_open = datetime(2025, 8, 4, 13, 30, tzinfo=_UTC)
        strat.on_bar(_bar("AAPL", ts_open, 100.0, 100.0))

        ts_entry = datetime(2025, 8, 4, 19, 51, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_entry, 100.0, 100.0))

        assert order is None

    def test_positive_return_returns_none(self) -> None:
        strat = _strat()

        ts_open = datetime(2025, 8, 4, 13, 30, tzinfo=_UTC)
        strat.on_bar(_bar("AAPL", ts_open, 100.0, 100.0))

        ts_entry = datetime(2025, 8, 4, 19, 51, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_entry, 100.0, 101.0))

        assert order is None


# ---------------------------------------------------------------------------
# Test 3: No entry outside the entry window
#   15:00 UTC = 11:00 EDT — before the 15:50 ET entry window
# ---------------------------------------------------------------------------

class TestNoEntryOutsideWindow:
    def test_bar_before_window_returns_none_even_if_drop_qualifies(self) -> None:
        strat = _strat({"loss_threshold_pct": 1.0})

        # Session-open bar
        ts_open = datetime(2025, 8, 4, 13, 30, tzinfo=_UTC)
        strat.on_bar(_bar("AAPL", ts_open, 100.0, 100.0))

        # 15:00 UTC = 11:00 EDT — outside entry window (before 15:50 ET)
        ts_outside = datetime(2025, 8, 4, 15, 0, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_outside, 100.0, 98.0))

        assert order is None

    def test_bar_at_16_00_et_is_excluded(self) -> None:
        """16:00 ET is the exclusive upper bound of the window (session_close_time)."""
        strat = _strat({"loss_threshold_pct": 1.0})

        ts_open = datetime(2025, 8, 4, 13, 30, tzinfo=_UTC)
        strat.on_bar(_bar("AAPL", ts_open, 100.0, 100.0))

        # 20:00 UTC = 16:00 EDT — excluded (window is [15:50, 16:00))
        ts_at_close = datetime(2025, 8, 4, 20, 0, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_at_close, 100.0, 98.0))

        assert order is None


# ---------------------------------------------------------------------------
# Test 4: No session open recorded before entry window
#
# Per the spec and code: if the *first* bar a symbol sees that day is already
# inside the entry window (>= 09:30 ET), it WILL be recorded as the session
# open (line 81-83). The intraday return is then computed from that bar's own
# open vs its close. This test documents that actual behavior.
# ---------------------------------------------------------------------------

class TestSessionOpenFromEntryWindowBar:
    def test_entry_window_bar_records_its_own_open_as_session_open(self) -> None:
        """When no earlier regular-session bar was seen, the entry-window bar
        itself records its open as the session open. Entry fires if that bar's
        close is down enough vs its own open."""
        strat = _strat({"loss_threshold_pct": 1.0})

        # No prior bar seen for this symbol today.
        # 19:51 UTC = 15:51 EDT — inside entry window AND >= 09:30 ET
        # open=100.0, close=98.5 → -1.5% drop from own open → BUY expected
        ts_entry = datetime(2025, 8, 4, 19, 51, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_entry, open_price=100.0, close_price=98.5))

        assert order is not None
        assert order.side == OrderSide.BUY

    def test_entry_window_bar_own_open_insufficient_drop_returns_none(self) -> None:
        """Same scenario but the bar's close is only -0.5% vs its own open."""
        strat = _strat({"loss_threshold_pct": 1.0})

        ts_entry = datetime(2025, 8, 4, 19, 51, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_entry, open_price=100.0, close_price=99.5))

        assert order is None


# ---------------------------------------------------------------------------
# Test 5: One entry per symbol per day
# ---------------------------------------------------------------------------

class TestOneEntryPerDay:
    def test_second_qualifying_bar_same_day_returns_none(self) -> None:
        strat = _strat({"loss_threshold_pct": 1.0})

        ts_open = datetime(2025, 8, 4, 13, 30, tzinfo=_UTC)
        strat.on_bar(_bar("AAPL", ts_open, 100.0, 100.0))

        # First entry-window bar → should return BUY
        ts1 = datetime(2025, 8, 4, 19, 51, tzinfo=_UTC)
        order1 = strat.on_bar(_bar("AAPL", ts1, 100.0, 98.5))
        assert order1 is not None
        assert order1.side == OrderSide.BUY

        # Second bar, same day, same window, qualifying drop → must return None
        ts2 = datetime(2025, 8, 4, 19, 55, tzinfo=_UTC)
        order2 = strat.on_bar(_bar("AAPL", ts2, 100.0, 97.0))
        assert order2 is None

    def test_entry_allowed_next_calendar_day(self) -> None:
        """Entry tracking resets on a new ET calendar day."""
        strat = _strat({"loss_threshold_pct": 1.0})

        # Day 1
        ts_open1 = datetime(2025, 8, 4, 13, 30, tzinfo=_UTC)
        strat.on_bar(_bar("AAPL", ts_open1, 100.0, 100.0))
        ts_entry1 = datetime(2025, 8, 4, 19, 51, tzinfo=_UTC)
        order1 = strat.on_bar(_bar("AAPL", ts_entry1, 100.0, 98.5))
        assert order1 is not None

        # Day 2 — no position recorded (strategy doesn't know if filled), but
        # the _entered_on guard should only block same-day re-entry.
        # Start a fresh session open for Aug 5.
        ts_open2 = datetime(2025, 8, 5, 13, 30, tzinfo=_UTC)
        strat.on_bar(_bar("AAPL", ts_open2, 100.0, 100.0))
        ts_entry2 = datetime(2025, 8, 5, 19, 51, tzinfo=_UTC)
        order2 = strat.on_bar(_bar("AAPL", ts_entry2, 100.0, 98.5))
        assert order2 is not None


# ---------------------------------------------------------------------------
# Test 6: Exit at next session open (EDT)
# ---------------------------------------------------------------------------

class TestExitAtNextOpen:
    def _setup_entry(self, strat: OvernightReversalStrategy) -> None:
        """Drive a real entry on Aug 4 to set _entered_on state."""
        ts_open = datetime(2025, 8, 4, 13, 30, tzinfo=_UTC)
        strat.on_bar(_bar("AAPL", ts_open, 100.0, 100.0))
        ts_entry = datetime(2025, 8, 4, 19, 51, tzinfo=_UTC)
        strat.on_bar(_bar("AAPL", ts_entry, 100.0, 98.5))

    def test_next_day_session_open_produces_sell(self) -> None:
        strat = _strat({"loss_threshold_pct": 1.0})
        self._setup_entry(strat)

        # Register the position so the strategy knows it's holding
        pos = _position("or_test", "AAPL", Decimal("41"),
                        opened_at=datetime(2025, 8, 4, 19, 51, tzinfo=_UTC))
        strat.update_position(pos)

        # Aug 5 at 13:30 UTC = 09:30 EDT → next-day session open → SELL
        ts_next_open = datetime(2025, 8, 5, 13, 30, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_next_open, 99.0, 99.0))

        assert order is not None
        assert order.side == OrderSide.SELL
        assert order.quantity == Decimal("41")

    def test_no_exit_same_day(self) -> None:
        strat = _strat({"loss_threshold_pct": 1.0})
        self._setup_entry(strat)

        pos = _position("or_test", "AAPL", Decimal("41"),
                        opened_at=datetime(2025, 8, 4, 19, 51, tzinfo=_UTC))
        strat.update_position(pos)

        # Aug 4 at 19:55 UTC — same day as entry → no exit
        ts_same_day = datetime(2025, 8, 4, 19, 55, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_same_day, 98.5, 98.0))

        assert order is None

    def test_no_exit_premarket_next_day(self) -> None:
        """13:00 UTC = 09:00 EDT — before regular session, must not exit."""
        strat = _strat({"loss_threshold_pct": 1.0})
        self._setup_entry(strat)

        pos = _position("or_test", "AAPL", Decimal("41"),
                        opened_at=datetime(2025, 8, 4, 19, 51, tzinfo=_UTC))
        strat.update_position(pos)

        # Aug 5 at 13:00 UTC = 09:00 EDT — premarket, before 09:30
        ts_premarket = datetime(2025, 8, 5, 13, 0, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_premarket, 99.0, 99.0))

        assert order is None


# ---------------------------------------------------------------------------
# Test 7: EST equivalence (January 2026) and DST boundary
#   In EST (UTC-5): 09:30 ET = 14:30 UTC, 15:51 ET = 20:51 UTC
#   In EDT (UTC-4): the same UTC 20:51 = 16:51 ET — outside entry window
# ---------------------------------------------------------------------------

class TestESTEquivalence:
    def test_entry_in_est_window(self) -> None:
        """January 2026: 20:51 UTC = 15:51 EST — inside entry window."""
        strat = _strat({"loss_threshold_pct": 1.0})

        # Session open: 14:30 UTC = 09:30 EST on Jan 5, 2026
        ts_open = datetime(2026, 1, 5, 14, 30, tzinfo=_UTC)
        strat.on_bar(_bar("AAPL", ts_open, 100.0, 100.0))

        # Entry window: 20:51 UTC = 15:51 EST
        ts_entry = datetime(2026, 1, 5, 20, 51, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_entry, 100.0, 98.5))

        assert order is not None
        assert order.side == OrderSide.BUY

    def test_same_utc_time_in_august_is_outside_window(self) -> None:
        """20:51 UTC in August = 16:51 EDT — past market close, outside window."""
        strat = _strat({"loss_threshold_pct": 1.0})

        # Session open: 13:30 UTC = 09:30 EDT on Aug 4, 2025
        ts_open = datetime(2025, 8, 4, 13, 30, tzinfo=_UTC)
        strat.on_bar(_bar("AAPL", ts_open, 100.0, 100.0))

        # 20:51 UTC in August = 16:51 EDT — past 16:00 ET, outside window
        ts_outside = datetime(2025, 8, 4, 20, 51, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_outside, 100.0, 98.5))

        assert order is None

    def test_est_session_open_recorded_at_correct_utc(self) -> None:
        """Session open should be recorded from 14:30 UTC in January (EST)."""
        strat = _strat({"loss_threshold_pct": 1.0})

        # 14:30 UTC = 09:30 EST
        ts_open = datetime(2026, 1, 5, 14, 30, tzinfo=_UTC)
        strat.on_bar(_bar("AAPL", ts_open, 105.0, 105.0))

        # Entry bar: 20:51 UTC = 15:51 EST, down >1% from 105.0
        ts_entry = datetime(2026, 1, 5, 20, 51, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_entry, 105.0, 103.5))

        assert order is not None
        assert order.side == OrderSide.BUY


# ---------------------------------------------------------------------------
# Test 8: allowed_symbols filtering
# ---------------------------------------------------------------------------

class TestAllowedSymbolsFilter:
    def test_symbol_not_in_whitelist_returns_none(self) -> None:
        strat = _strat({"allowed_symbols": ["AAPL"], "loss_threshold_pct": 1.0})

        # MSFT is not in the whitelist — should be filtered before any logic
        ts_entry = datetime(2025, 8, 4, 19, 51, tzinfo=_UTC)
        order = strat.on_bar(_bar("MSFT", ts_entry, 100.0, 98.0))

        assert order is None

    def test_symbol_in_whitelist_is_processed(self) -> None:
        strat = _strat({"allowed_symbols": ["AAPL", "MSFT"], "loss_threshold_pct": 1.0})

        ts_open = datetime(2025, 8, 4, 13, 30, tzinfo=_UTC)
        strat.on_bar(_bar("AAPL", ts_open, 100.0, 100.0))

        ts_entry = datetime(2025, 8, 4, 19, 51, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_entry, 100.0, 98.5))

        assert order is not None

    def test_no_filter_when_allowed_symbols_not_configured(self) -> None:
        strat = _strat({"loss_threshold_pct": 1.0})
        assert strat.allowed_symbols is None

        ts_open = datetime(2025, 8, 4, 13, 30, tzinfo=_UTC)
        strat.on_bar(_bar("NVDA", ts_open, 100.0, 100.0))

        ts_entry = datetime(2025, 8, 4, 19, 51, tzinfo=_UTC)
        order = strat.on_bar(_bar("NVDA", ts_entry, 100.0, 98.5))

        assert order is not None

    def test_blocked_symbol_does_not_record_session_state(self) -> None:
        strat = _strat({"allowed_symbols": ["AAPL"]})

        ts_open = datetime(2025, 8, 4, 13, 30, tzinfo=_UTC)
        strat.on_bar(_bar("MSFT", ts_open, 100.0, 100.0))

        # The blocked symbol should not pollute internal session state
        assert "MSFT" not in strat._session_date


# ---------------------------------------------------------------------------
# Test 9: Capacity guard
# ---------------------------------------------------------------------------

class TestCapacityGuard:
    def test_at_capacity_blocks_new_entry(self) -> None:
        strat = _strat({"max_positions": 1, "loss_threshold_pct": 1.0})

        # Record an existing position in a different symbol
        pos = _position("or_test", "MSFT", Decimal("100"),
                        opened_at=datetime(2025, 8, 3, 19, 51, tzinfo=_UTC))
        strat.update_position(pos)

        # Now try to enter AAPL — should be blocked by capacity
        ts_open = datetime(2025, 8, 4, 13, 30, tzinfo=_UTC)
        strat.on_bar(_bar("AAPL", ts_open, 100.0, 100.0))

        ts_entry = datetime(2025, 8, 4, 19, 51, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_entry, 100.0, 98.5))

        assert order is None

    def test_capacity_allows_entry_when_not_full(self) -> None:
        strat = _strat({"max_positions": 2, "loss_threshold_pct": 1.0})

        pos = _position("or_test", "MSFT", Decimal("100"),
                        opened_at=datetime(2025, 8, 3, 19, 51, tzinfo=_UTC))
        strat.update_position(pos)

        ts_open = datetime(2025, 8, 4, 13, 30, tzinfo=_UTC)
        strat.on_bar(_bar("AAPL", ts_open, 100.0, 100.0))

        ts_entry = datetime(2025, 8, 4, 19, 51, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_entry, 100.0, 98.5))

        assert order is not None
        assert order.side == OrderSide.BUY


# ---------------------------------------------------------------------------
# Test 10: Exit with lost state (fallback via position.opened_at)
# ---------------------------------------------------------------------------

class TestExitWithLostState:
    def test_exit_fires_via_opened_at_fallback(self) -> None:
        """_entered_on is empty (e.g. after restart), but position.opened_at
        is set to a previous day. The strategy should still exit on the next
        session open using the fallback path."""
        strat = _strat({"loss_threshold_pct": 1.0})

        # Do NOT drive an entry — _entered_on stays empty
        assert strat._entered_on == {}

        # Position was opened on Aug 4 (previous day)
        pos = _position("or_test", "AAPL", Decimal("41"),
                        opened_at=datetime(2025, 8, 4, 19, 51, tzinfo=_UTC))
        strat.update_position(pos)

        # Aug 5 at 13:30 UTC = 09:30 EDT → next-day session open → SELL via fallback
        ts_next_open = datetime(2025, 8, 5, 13, 30, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_next_open, 99.0, 99.0))

        assert order is not None
        assert order.side == OrderSide.SELL
        assert order.quantity == Decimal("41")

    def test_no_exit_same_day_via_opened_at_fallback(self) -> None:
        """Even with the fallback path, same-day bars must not trigger exit."""
        strat = _strat({"loss_threshold_pct": 1.0})

        # Position opened the same day we're testing
        pos = _position("or_test", "AAPL", Decimal("41"),
                        opened_at=datetime(2025, 8, 5, 19, 51, tzinfo=_UTC))
        strat.update_position(pos)

        # Bar on Aug 5 later — same day as opened_at → no exit
        ts_same = datetime(2025, 8, 5, 19, 55, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_same, 99.0, 98.5))

        assert order is None

    def test_exit_with_lost_state_premarket_still_blocked(self) -> None:
        """Fallback exit must also respect the 09:30 ET gate."""
        strat = _strat({"loss_threshold_pct": 1.0})

        pos = _position("or_test", "AAPL", Decimal("41"),
                        opened_at=datetime(2025, 8, 4, 19, 51, tzinfo=_UTC))
        strat.update_position(pos)

        # Aug 5 at 13:00 UTC = 09:00 EDT — premarket
        ts_premarket = datetime(2025, 8, 5, 13, 0, tzinfo=_UTC)
        order = strat.on_bar(_bar("AAPL", ts_premarket, 99.0, 99.0))

        assert order is None
