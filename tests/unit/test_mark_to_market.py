"""Tests for mark_to_market_daily equity curve construction."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from axtrade.fulltest.analytics import mark_to_market_daily


# -- helpers --


def _fill(symbol, side, quantity, price, commission, fill_date):
    """Return a fill row dict with filled_at set to midnight UTC on fill_date."""
    return {
        "strategy_id": "test",
        "symbol": symbol,
        "side": side,
        "quantity": Decimal(str(quantity)),
        "price": Decimal(str(price)),
        "commission": Decimal(str(commission)),
        "filled_at": datetime(fill_date.year, fill_date.month, fill_date.day,
                              12, 0, 0, tzinfo=timezone.utc),
    }


def _closes(symbol, *day_close_pairs):
    """Build daily_closes dict for a single symbol from (date, close) pairs."""
    return {symbol: {d: Decimal(str(c)) for d, c in day_close_pairs}}


def _merge_closes(*dicts):
    """Merge multiple single-symbol close dicts into one daily_closes mapping."""
    result = {}
    for d in dicts:
        result.update(d)
    return result


# Shared dates used across multiple tests
D0 = date(2025, 8, 31)   # start_date / day-zero (no closes)
D1 = date(2025, 9, 1)    # day 1 — first trading day / buy day
D2 = date(2025, 9, 2)    # day 2
D3 = date(2025, 9, 3)    # day 3


# -- buy-and-hold --


def test_buy_and_hold_equity_values():
    """One buy fill on day 1; closing prices 100/110/90 over three days.

    Expected equity:
      day-zero  : initial_capital  (synthetic start point, D0 has no closes)
      day 1     : initial - 41*100 - 1 + 41*100  = initial - 1
      day 2     : initial - 1 + 41*(110-100)     = initial - 1 + 410
      day 3     : initial - 1 - 41*(100-90)      = initial - 1 - 410
                  (relative to day 1 close, loses 41*10 vs the 110 peak)
    """
    initial = Decimal("100000")
    rows = [_fill("AAPL", "buy", 41, 100, 1, D1)]
    closes = _closes("AAPL", (D1, 100), (D2, 110), (D3, 90))

    curve = mark_to_market_daily(rows, initial, closes, start_date=D0, end_date=D3)

    # Curve: [D0 synthetic, D1, D2, D3]
    assert len(curve) == 4

    # Day-zero synthetic point
    assert curve[0].equity == initial
    assert curve[0].drawdown == Decimal("0")
    assert curve[0].timestamp.date() == D0

    # Day 1: cash = 100000 - 41*100 - 1 = 95899; position = 41*100 = 4100
    assert curve[1].equity == Decimal("99999")   # initial - 1
    assert curve[1].timestamp.date() == D1

    # Day 2: cash unchanged = 95899; position = 41*110 = 4510
    assert curve[2].equity == Decimal("100409")  # initial - 1 + 410
    assert curve[2].timestamp.date() == D2

    # Day 3: cash unchanged = 95899; position = 41*90 = 3690
    assert curve[3].equity == Decimal("99589")   # initial - 1 - 410
    assert curve[3].timestamp.date() == D3


def test_buy_and_hold_day_zero_is_synthetic():
    """D0 has no close entry, so the day-zero point is always initial_capital."""
    initial = Decimal("50000")
    rows = [_fill("AAPL", "buy", 10, 100, 0, D1)]
    closes = _closes("AAPL", (D1, 100), (D2, 105))

    curve = mark_to_market_daily(rows, initial, closes, start_date=D0, end_date=D2)

    assert curve[0].equity == initial
    assert curve[0].timestamp.date() == D0


# -- round trip --


def test_round_trip_equity_flat_after_close():
    """Buy on D1 @ 100, sell on D2 @ 110; D3 has no position so equity stays put.

    Round-trip P&L = 41*(110-100) - 1 - 1 = 408.
    Day-2 equity = initial + 408.
    Day-3 equity = same (no open position, no more fills).
    """
    initial = Decimal("100000")
    rows = [
        _fill("AAPL", "buy", 41, 100, 1, D1),
        _fill("AAPL", "sell", 41, 110, 1, D2),
    ]
    closes = _closes("AAPL", (D1, 100), (D2, 110), (D3, 90))

    curve = mark_to_market_daily(rows, initial, closes, start_date=D0, end_date=D3)

    assert len(curve) == 4

    # Day 1: cash = 100000 - 41*100 - 1 = 95899; position = 41*100 = 4100
    assert curve[1].equity == Decimal("99999")

    # Day 2: sell fills first → cash = 95899 + 41*110 - 1 = 100408; qty=0
    assert curve[2].equity == Decimal("100408")  # initial + 41*10 - 2

    # Day 3: no position, no fills → equity unchanged
    assert curve[3].equity == Decimal("100408")


def test_round_trip_commissions_deducted():
    """Commissions from both sides reduce final equity."""
    initial = Decimal("100000")
    rows = [
        _fill("AAPL", "buy", 41, 100, 1, D1),
        _fill("AAPL", "sell", 41, 110, 1, D2),
    ]
    closes = _closes("AAPL", (D1, 100), (D2, 110))

    curve = mark_to_market_daily(rows, initial, closes, start_date=D0, end_date=D2)

    final = curve[-1].equity
    # Gross P&L = 41*10 = 410; net after 2 commissions = 408
    assert final == initial + Decimal("408")


# -- carry-forward: symbol with gaps in closes --


def test_carry_forward_missing_close_uses_last_known():
    """AAPL has closes on D1 and D3 only (gap on D2).

    A second symbol (MSFT) has closes on all three days so that D2 appears
    in all_days.  AAPL's D2 position should be valued at the D1 close (100),
    not skipped.
    """
    initial = Decimal("100000")
    rows = [_fill("AAPL", "buy", 10, 100, 0, D1)]

    aapl_closes = {D1: Decimal("100"), D3: Decimal("120")}
    msft_closes = {D1: Decimal("200"), D2: Decimal("210"), D3: Decimal("205")}
    closes = {"AAPL": aapl_closes, "MSFT": msft_closes}

    curve = mark_to_market_daily(rows, initial, closes, start_date=D0, end_date=D3)

    # all_days = [D1, D2, D3] because MSFT provides D2
    assert len(curve) == 4  # D0 synthetic + D1 + D2 + D3

    # D1: cash = 100000 - 1000; position = 10*100 = 1000; equity = 100000
    assert curve[1].equity == Decimal("100000")

    # D2: AAPL has no close → carry D1 close (100); position = 10*100 = 1000
    assert curve[2].equity == Decimal("100000")

    # D3: AAPL close = 120; position = 10*120 = 1200; cash = 99000
    assert curve[3].equity == Decimal("100200")


def test_carry_forward_not_applied_before_any_close_seen():
    """If a symbol has no close on D1 but we open a position, D1 value is skipped
    (last_close not yet set), and carry starts from first seen close.
    """
    initial = Decimal("100000")
    rows = [_fill("AAPL", "buy", 10, 100, 0, D1)]

    # AAPL close only available from D2 onward; MSFT provides D1 day
    aapl_closes = {D2: Decimal("105"), D3: Decimal("110")}
    msft_closes = {D1: Decimal("200"), D2: Decimal("200"), D3: Decimal("200")}
    closes = {"AAPL": aapl_closes, "MSFT": msft_closes}

    curve = mark_to_market_daily(rows, initial, closes, start_date=D0, end_date=D3)

    # D1: AAPL has no close and last_close not set → skipped from position_value
    # cash = 99000; position_value = 0 (AAPL) + 0 (no MSFT position)
    assert curve[1].equity == Decimal("99000")

    # D2: AAPL close = 105 → position_value = 10*105 = 1050
    assert curve[2].equity == Decimal("100050")


# -- drawdown --


def test_drawdown_positive_when_below_peak():
    """After price rises then falls, drawdown should be positive."""
    initial = Decimal("100000")
    rows = [_fill("AAPL", "buy", 100, 100, 0, D1)]
    closes = _closes("AAPL", (D1, 100), (D2, 110), (D3, 90))

    curve = mark_to_market_daily(rows, initial, closes, start_date=D0, end_date=D3)

    # D1: equity = 100000 (no change, cost = market value); peak = 100000; dd = 0
    assert curve[1].drawdown == Decimal("0")

    # D2: equity = 100000 + 100*10 = 101000; new peak = 101000; dd = 0
    assert curve[2].equity == Decimal("101000")
    assert curve[2].drawdown == Decimal("0")

    # D3: equity = 100000 - 100*10 = 99000; peak = 101000
    # dd = (101000-99000)/101000 * 100 ≈ 1.980...%
    assert curve[3].equity == Decimal("99000")
    expected_dd = (Decimal("101000") - Decimal("99000")) / Decimal("101000") * 100
    assert curve[3].drawdown == pytest.approx(expected_dd, abs=Decimal("0.001"))


def test_drawdown_zero_at_day_zero():
    """Synthetic day-zero point always has zero drawdown."""
    initial = Decimal("100000")
    rows = []
    closes = _closes("AAPL", (D1, 100))

    curve = mark_to_market_daily(rows, initial, closes, start_date=D0, end_date=D1)

    assert curve[0].drawdown == Decimal("0")


# -- date filtering --


def test_closes_outside_window_excluded():
    """Closes before start_date or after end_date are not included in the curve."""
    initial = Decimal("100000")
    rows = [_fill("AAPL", "buy", 10, 100, 0, D1)]

    before = date(2025, 8, 1)
    after = date(2025, 9, 30)
    closes = {
        "AAPL": {
            before: Decimal("80"),
            D1: Decimal("100"),
            D2: Decimal("110"),
            after: Decimal("200"),
        }
    }

    curve = mark_to_market_daily(rows, initial, closes, start_date=D0, end_date=D2)

    # Only D0 (synthetic), D1, D2 appear; `before` and `after` are outside window
    days_in_curve = [pt.timestamp.date() for pt in curve]
    assert before not in days_in_curve
    assert after not in days_in_curve
    assert len(curve) == 3  # D0, D1, D2


def test_end_date_is_inclusive():
    """end_date day appears in the curve."""
    initial = Decimal("100000")
    rows = []
    closes = _closes("AAPL", (D1, 100), (D2, 110), (D3, 120))

    curve = mark_to_market_daily(rows, initial, closes, start_date=D0, end_date=D3)

    days = [pt.timestamp.date() for pt in curve]
    assert D3 in days


# -- fill row types (Decimal and float-ish values) --


def test_fill_rows_with_float_quantity_and_price():
    """quantity and price may be plain floats/ints coming from dict construction."""
    initial = Decimal("100000")
    rows = [
        {
            "strategy_id": "test",
            "symbol": "AAPL",
            "side": "buy",
            "quantity": 10,          # plain int
            "price": 100.0,           # plain float
            "commission": 1.5,
            "filled_at": datetime(2025, 9, 1, 12, 0, 0, tzinfo=timezone.utc),
        }
    ]
    closes = _closes("AAPL", (D1, 105))

    curve = mark_to_market_daily(rows, initial, closes, start_date=D0, end_date=D1)

    # cash = 100000 - 10*100 - 1.5 = 98998.5; position = 10*105 = 1050
    assert curve[1].equity == pytest.approx(Decimal("100048.5"), abs=Decimal("0.01"))


# -- empty cases --


def test_no_fills_equity_flat_at_initial_capital():
    """With no fills, every day's equity equals initial_capital."""
    initial = Decimal("100000")
    rows = []
    closes = _closes("AAPL", (D1, 100), (D2, 110), (D3, 90))

    curve = mark_to_market_daily(rows, initial, closes, start_date=D0, end_date=D3)

    for pt in curve:
        assert pt.equity == initial


def test_empty_daily_closes_returns_only_day_zero():
    """When daily_closes has no entries in the window, only the synthetic point exists."""
    initial = Decimal("100000")
    rows = []

    curve = mark_to_market_daily(rows, initial, {}, start_date=D0, end_date=D3)

    assert len(curve) == 1
    assert curve[0].equity == initial
