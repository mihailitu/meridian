"""Tests for fulltest analytics module."""

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from axtrade.backtest.types import EquityPoint, TradeRecord
from axtrade.fulltest.analytics import (
    SymbolStats,
    _process_fills,
    build_equity_curve,
    build_trade_records,
    resample_equity_daily,
)


# -- helpers --


def _make_fill_row(strategy_id, symbol, side, quantity, price, commission, filled_at):
    """Create a dict mimicking an asyncpg Row for fills."""
    return {
        "strategy_id": strategy_id,
        "symbol": symbol,
        "side": side,
        "quantity": Decimal(str(quantity)),
        "price": Decimal(str(price)),
        "commission": Decimal(str(commission)),
        "filled_at": filled_at,
    }


class FakeConnection:
    """Minimal async connection stub returning preset rows.

    Routes by SQL content so that fills queries and the daily-closes bars
    query (added in Phase 2.8) don't cross-contaminate each other.
    """

    def __init__(self, rows, realized_pnl=Decimal("0")):
        self._rows = rows
        self._realized_pnl = realized_pnl

    async def fetch(self, query, *args):
        # _fetch_daily_closes queries the bars table; return empty so that
        # compute_analytics falls back to the cost-basis curve in tests that
        # don't need mark-to-market.
        if "FROM bars" in query:
            return []
        # _fetch_fills queries the fills table, optionally with a strategy filter
        if args:
            strategy_id = args[0]
            return [r for r in self._rows if r["strategy_id"] == strategy_id]
        return self._rows

    async def fetchval(self, query, *args):
        return self._realized_pnl


@pytest.fixture
def simple_fills():
    """Buy 100@50, Sell 100@55 -- basic round trip."""
    return [
        _make_fill_row(
            "momentum-bt", "AAPL", "buy", 100, 50, 1.00,
            datetime(2025, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
        ),
        _make_fill_row(
            "momentum-bt", "AAPL", "sell", 100, 55, 1.00,
            datetime(2025, 9, 1, 14, 0, 0, tzinfo=timezone.utc),
        ),
    ]


@pytest.fixture
def partial_fills():
    """Buy 100@50, Sell 50@55, Sell 50@60 -- partial fill FIFO matching."""
    return [
        _make_fill_row(
            "momentum-bt", "AAPL", "buy", 100, 50, 2.00,
            datetime(2025, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
        ),
        _make_fill_row(
            "momentum-bt", "AAPL", "sell", 50, 55, 1.00,
            datetime(2025, 9, 1, 14, 0, 0, tzinfo=timezone.utc),
        ),
        _make_fill_row(
            "momentum-bt", "AAPL", "sell", 50, 60, 1.00,
            datetime(2025, 9, 2, 10, 0, 0, tzinfo=timezone.utc),
        ),
    ]


# -- build_trade_records tests --


async def test_build_trade_records_fifo_matching(simple_fills):
    conn = FakeConnection(simple_fills)
    trades = await build_trade_records(conn, strategy_id="momentum-bt")

    assert len(trades) == 2

    # Buy has no P&L
    assert trades[0].side == "BUY"
    assert trades[0].pnl is None
    assert trades[0].quantity == Decimal("100")
    assert trades[0].price == Decimal("50")

    # Sell: P&L = (55 - 50) * 100 - 1.00 (buy commission) - 1.00 (sell commission) = 498
    assert trades[1].side == "SELL"
    assert trades[1].pnl == Decimal("498.00")


async def test_build_trade_records_partial_fills(partial_fills):
    conn = FakeConnection(partial_fills)
    trades = await build_trade_records(conn, strategy_id="momentum-bt")

    assert len(trades) == 3
    assert trades[0].side == "BUY"
    assert trades[0].pnl is None

    # First sell: 50@55 vs 50 of the 100@50 buy lot
    # P&L = (55-50)*50 - (2.00 * 50/100) - 1.00 = 250 - 1.00 - 1.00 = 248.00
    assert trades[1].side == "SELL"
    assert trades[1].pnl == Decimal("248.00")

    # Second sell: 50@60 vs remaining 50 of the 100@50 buy lot
    # P&L = (60-50)*50 - (2.00 * 50/100) - 1.00 = 500 - 1.00 - 1.00 = 498.00
    assert trades[2].side == "SELL"
    assert trades[2].pnl == Decimal("498.00")


async def test_build_trade_records_no_fills():
    conn = FakeConnection([])
    trades = await build_trade_records(conn, strategy_id="momentum-bt")
    assert trades == []


async def test_build_trade_records_all_strategies(simple_fills):
    conn = FakeConnection(simple_fills)
    trades = await build_trade_records(conn, strategy_id=None)
    assert len(trades) == 2


# -- _process_fills equity curve tests (precise path) --


def test_process_fills_equity_basic(simple_fills):
    initial = Decimal("100000")
    trades, curve, _ = _process_fills(simple_fills, initial)

    assert len(curve) == 2
    # After buy: cash = 100000 - (50*100 + 1) = 94999, open_cost = 5000
    # equity = 94999 + 5000 = 99999
    assert curve[0].equity == Decimal("99999")
    # After sell: cash = 94999 + (55*100 - 1) = 100498, open_cost = 0
    # equity = 100498
    assert curve[1].equity == Decimal("100498")


def test_process_fills_equity_drawdown():
    rows = [
        _make_fill_row(
            "test", "AAPL", "buy", 100, 50, 0,
            datetime(2025, 9, 1, 10, 0, tzinfo=timezone.utc),
        ),
        _make_fill_row(
            "test", "AAPL", "sell", 100, 45, 0,
            datetime(2025, 9, 1, 14, 0, tzinfo=timezone.utc),
        ),
    ]
    initial = Decimal("100000")
    trades, curve, _ = _process_fills(rows, initial)

    assert len(curve) == 2
    # After buy: cash = 95000, cost = 5000, equity = 100000, dd = 0
    assert curve[0].equity == Decimal("100000")
    assert curve[0].drawdown == Decimal("0")
    # After sell: cash = 95000 + 4500 = 99500, cost = 0, equity = 99500
    # peak = 100000, dd = 500/100000 * 100 = 0.5%
    assert curve[1].equity == Decimal("99500")
    assert curve[1].drawdown == Decimal("0.5")


def test_process_fills_empty():
    trades, curve, _ = _process_fills([], Decimal("100000"))
    assert trades == []
    assert curve == []


def test_process_fills_unmatched_sell_does_not_inflate_equity():
    """Sell without matching buy should not inflate equity beyond initial capital."""
    rows = [
        _make_fill_row(
            "test", "AAPL", "sell", 100, 55, 1.00,
            datetime(2025, 9, 1, 14, 0, 0, tzinfo=timezone.utc),
        ),
    ]
    initial = Decimal("100000")
    trades, curve, _ = _process_fills(rows, initial)

    assert len(curve) == 1
    # Unmatched sell: cash += 55*100 - 1 = 5499, open_position_cost -= 55*100 = -5500
    # equity = (100000 + 5499) + (-5500) = 99999
    # Should NOT be 105499 (the old broken behavior)
    assert curve[0].equity == Decimal("99999")


def test_process_fills_partial_unmatched_sell():
    """Buy 50 then sell 100: first 50 matched, remaining 50 unmatched."""
    rows = [
        _make_fill_row(
            "test", "AAPL", "buy", 50, 50, 1.00,
            datetime(2025, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
        ),
        _make_fill_row(
            "test", "AAPL", "sell", 100, 55, 1.00,
            datetime(2025, 9, 1, 14, 0, 0, tzinfo=timezone.utc),
        ),
    ]
    initial = Decimal("100000")
    trades, curve, _ = _process_fills(rows, initial)

    assert len(curve) == 2
    # After buy: cash = 100000 - 2501 = 97499, cost = 2500, equity = 99999
    assert curve[0].equity == Decimal("99999")
    # After sell: 50 matched (cost_basis_sold = 50*50 = 2500),
    # 50 unmatched (cost_basis_sold += 55*50 = 2750), total cost_basis_sold = 5250
    # cash = 97499 + (55*100 - 1) = 102998
    # open_cost = 2500 - 5250 = -2750
    # equity = 102998 + (-2750) = 100248
    # That's (55-50)*50 - 1(buy_comm) - 1(sell_comm) = 248 profit on matched portion
    assert curve[1].equity == Decimal("100248")


# -- per-symbol stats tests --


def test_per_symbol_stats_winning_round_trip():
    rows = [
        _make_fill_row(
            "test", "AAPL", "buy", 100, 50, 0,
            datetime(2025, 9, 1, 10, 0, tzinfo=timezone.utc),
        ),
        _make_fill_row(
            "test", "AAPL", "sell", 100, 55, 0,
            datetime(2025, 9, 1, 14, 0, tzinfo=timezone.utc),
        ),
    ]
    _, _, per_symbol = _process_fills(rows, Decimal("100000"))

    assert "AAPL" in per_symbol
    aapl = per_symbol["AAPL"]
    assert aapl.pnl == Decimal("500")  # (55-50) * 100
    assert aapl.trades == 1
    assert aapl.wins == 1
    assert aapl.losses == 0


def test_per_symbol_stats_multi_symbol_segregation():
    """Stats are tracked per symbol, not per-strategy aggregate."""
    rows = [
        # AAPL: winning round trip
        _make_fill_row("test", "AAPL", "buy", 100, 50, 0,
                       datetime(2025, 9, 1, 10, 0, tzinfo=timezone.utc)),
        _make_fill_row("test", "AAPL", "sell", 100, 55, 0,
                       datetime(2025, 9, 1, 14, 0, tzinfo=timezone.utc)),
        # MSFT: losing round trip
        _make_fill_row("test", "MSFT", "buy", 50, 200, 0,
                       datetime(2025, 9, 2, 10, 0, tzinfo=timezone.utc)),
        _make_fill_row("test", "MSFT", "sell", 50, 195, 0,
                       datetime(2025, 9, 2, 14, 0, tzinfo=timezone.utc)),
    ]
    _, _, per_symbol = _process_fills(rows, Decimal("100000"))

    assert per_symbol["AAPL"].pnl == Decimal("500")
    assert per_symbol["AAPL"].wins == 1
    assert per_symbol["MSFT"].pnl == Decimal("-250")  # (195-200) * 50
    assert per_symbol["MSFT"].losses == 1


def test_per_symbol_stats_unmatched_sell_skipped():
    """Sells without a matching buy don't count as round-trips in per-symbol."""
    rows = [
        _make_fill_row("test", "AAPL", "sell", 100, 55, 0,
                       datetime(2025, 9, 1, 14, 0, tzinfo=timezone.utc)),
    ]
    _, _, per_symbol = _process_fills(rows, Decimal("100000"))
    assert per_symbol == {}


def test_per_symbol_stats_open_position_not_counted():
    """An unclosed buy doesn't show up in per-symbol stats yet."""
    rows = [
        _make_fill_row("test", "AAPL", "buy", 100, 50, 0,
                       datetime(2025, 9, 1, 10, 0, tzinfo=timezone.utc)),
    ]
    _, _, per_symbol = _process_fills(rows, Decimal("100000"))
    # Buy alone produces no closed round-trip, so per-symbol is empty.
    assert per_symbol == {}


# -- standalone build_equity_curve tests --


def test_build_equity_curve_empty():
    curve = build_equity_curve([], Decimal("100000"))
    assert curve == []


def test_build_equity_curve_buy_reduces_equity_by_commission():
    trades = [
        TradeRecord(
            timestamp=datetime(2025, 9, 1, 10, 0, tzinfo=timezone.utc),
            side="BUY", quantity=Decimal("100"), price=Decimal("50"),
            commission=Decimal("5"), pnl=None,
        ),
    ]
    curve = build_equity_curve(trades, Decimal("100000"))
    assert len(curve) == 1
    # Buy reduces equity by commission only
    assert curve[0].equity == Decimal("99995")


# -- resample_equity_daily tests --


def test_resample_equity_daily():
    points = [
        EquityPoint(
            timestamp=datetime(2025, 9, 1, 10, 0, tzinfo=timezone.utc),
            equity=Decimal("100000"),
            drawdown=Decimal("0"),
        ),
        EquityPoint(
            timestamp=datetime(2025, 9, 1, 14, 0, tzinfo=timezone.utc),
            equity=Decimal("100500"),
            drawdown=Decimal("0"),
        ),
        EquityPoint(
            timestamp=datetime(2025, 9, 2, 10, 0, tzinfo=timezone.utc),
            equity=Decimal("101000"),
            drawdown=Decimal("0"),
        ),
    ]

    daily = resample_equity_daily(points)

    # Two intraday points on Sep 1 collapse to one
    assert len(daily) == 2
    assert daily[0].timestamp == datetime(2025, 9, 1, 14, 0, tzinfo=timezone.utc)
    assert daily[0].equity == Decimal("100500")
    assert daily[1].timestamp == datetime(2025, 9, 2, 10, 0, tzinfo=timezone.utc)


def test_resample_equity_daily_empty():
    assert resample_equity_daily([]) == []


def test_resample_equity_daily_prepends_initial_capital():
    """When start_date precedes first fill, a synthetic day-zero point is prepended."""
    points = [
        EquityPoint(
            timestamp=datetime(2025, 9, 2, 14, 0, tzinfo=timezone.utc),
            equity=Decimal("100500"),
            drawdown=Decimal("0"),
        ),
    ]
    daily = resample_equity_daily(
        points,
        initial_capital=Decimal("100000"),
        start_date=date(2025, 9, 1),
    )
    assert len(daily) == 2
    assert daily[0].equity == Decimal("100000")
    assert daily[1].equity == Decimal("100500")


def test_resample_equity_daily_no_duplicate_start():
    """When fills already start on start_date, no synthetic point is added."""
    points = [
        EquityPoint(
            timestamp=datetime(2025, 9, 1, 14, 0, tzinfo=timezone.utc),
            equity=Decimal("100500"),
            drawdown=Decimal("0"),
        ),
    ]
    daily = resample_equity_daily(
        points,
        initial_capital=Decimal("100000"),
        start_date=date(2025, 9, 1),
    )
    # Should not duplicate -- fill on Sep 1 already covers that date
    assert len(daily) == 1
    assert daily[0].equity == Decimal("100500")


# -- compute_analytics end-to-end test --


async def test_compute_analytics_end_to_end(simple_fills):
    from axtrade.fulltest.analytics import compute_analytics

    # P&L = (55-50)*100 - 1 - 1 = 498
    conn = FakeConnection(simple_fills, realized_pnl=Decimal("498"))
    metrics = await compute_analytics(
        conn,
        strategy_id="momentum-bt",
        initial_capital=100000.0,
        start_date=date(2025, 8, 1),
        end_date=date(2026, 2, 1),
    )

    expected_keys = {
        "total_trades", "winning_trades", "losing_trades", "win_rate",
        "total_return", "annualized_return", "sharpe_ratio", "max_drawdown",
        "profit_factor", "avg_trade_pnl", "avg_winner", "avg_loser",
        "total_commission",
    }
    assert expected_keys.issubset(set(metrics.keys()))

    # 1 closing trade (the sell), which is a winner
    assert metrics["total_trades"] == 1
    assert metrics["winning_trades"] == 1
    assert metrics["losing_trades"] == 0
    assert metrics["win_rate"] == 100.0
    assert metrics["profit_factor"] == float("inf")
    # total_return now comes from positions table (498 / 100000 * 100 = 0.498%)
    assert metrics["total_return"] == pytest.approx(0.498, abs=0.001)


async def test_compute_analytics_no_fills():
    from axtrade.fulltest.analytics import compute_analytics

    conn = FakeConnection([])
    metrics = await compute_analytics(
        conn,
        strategy_id="empty-bt",
        initial_capital=100000.0,
        start_date=date(2025, 8, 1),
        end_date=date(2026, 2, 1),
    )

    assert metrics["total_trades"] == 0
    assert metrics["sharpe_ratio"] == 0.0
    assert metrics["max_drawdown"] == 0.0


async def test_compute_analytics_short_period_no_overflow():
    """Short backtest (4 days) should not produce astronomical annualized return."""
    from axtrade.fulltest.analytics import compute_analytics

    fills = [
        _make_fill_row(
            "test-bt", "AAPL", "buy", 100, 200, 1.00,
            datetime(2025, 9, 1, 10, 0, 0, tzinfo=timezone.utc),
        ),
        _make_fill_row(
            "test-bt", "AAPL", "sell", 100, 198, 1.00,
            datetime(2025, 9, 4, 14, 0, 0, tzinfo=timezone.utc),
        ),
    ]
    # Loss: (198-200)*100 - 1 - 1 = -202
    conn = FakeConnection(fills, realized_pnl=Decimal("-202"))
    metrics = await compute_analytics(
        conn,
        strategy_id="test-bt",
        initial_capital=100000.0,
        start_date=date(2025, 9, 1),
        end_date=date(2025, 9, 5),
    )

    # For 4-day backtest (< 0.25 years), annualized = raw return
    assert abs(metrics["annualized_return"]) < 1000
    assert metrics["total_return"] == pytest.approx(-0.202, abs=0.001)
    # annualized should equal total_return for short periods
    assert metrics["annualized_return"] == metrics["total_return"]


# -- win_rate property fix test --


def test_strategy_result_win_rate_uses_closed_trades():
    from axtrade.fulltest.types import StrategyResult

    sr = StrategyResult(
        strategy_id="test",
        strategy_type="momentum",
        trade_count=10,  # includes buys
        win_count=3,
        loss_count=2,
    )
    # win_rate should be 3 / (3+2) = 0.6, not 3/10
    assert sr.win_rate == 0.6
