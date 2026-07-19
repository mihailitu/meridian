"""Unit tests for the Phase 6 Phase C cross-sectional engine (xsect.py).

Synthetic-frame tests of the pre-registered spec's arithmetic
(docs/phase6-preregistration.md): signal orientation, pool filters, gap
guard, entry/exit conventions and fallbacks, tranche overlap accounting,
costs, NW t-stats, the advance rule, and no-look-ahead.
"""

import numpy as np
import pandas as pd
import pytest

from axtrade.research.xsect import (
    BINDING_BP,
    CellSpec,
    IS_QUARTERS,
    Pivots,
    compute_signal,
    evaluate_advance,
    formation_pool,
    guard_exclusions,
    nw_tstat,
    preregistered_cells,
    quarterly_table,
    simulate_cell,
    CellResult,
)

N_SYMBOLS = 20  # 2 names per decile


def make_calendar(n_days: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2024-08-01", periods=n_days)


def make_pivots(
    n_days: int,
    *,
    close: pd.DataFrame | None = None,
    open_: pd.DataFrame | None = None,
    bar1600: pd.DataFrame | None = None,
    eligible: pd.DataFrame | None = None,
    intraday_by_symbol: dict[str, float] | None = None,
) -> Pivots:
    """Build a Pivots fixture. Defaults: flat $100 prices, all eligible.

    intraday_by_symbol shifts each symbol's rth_close so that
    intraday_ret = close/open - 1 equals the given value every day.
    """
    calendar = make_calendar(n_days)
    symbols = [f"S{i:02d}" for i in range(N_SYMBOLS)]
    if open_ is None:
        open_ = pd.DataFrame(100.0, index=calendar, columns=symbols)
    if close is None:
        close = open_.copy()
        if intraday_by_symbol:
            for sym, r in intraday_by_symbol.items():
                close[sym] = open_[sym] * (1.0 + r)
    if bar1600 is None:
        bar1600 = close.copy()
    if eligible is None:
        eligible = pd.DataFrame(True, index=calendar, columns=symbols)
    prev_close = close.shift(1)
    gap = open_ / prev_close - 1
    intraday = close / open_ - 1
    return Pivots(
        calendar=calendar,
        open=open_,
        close=close,
        bar1600=bar1600,
        gap=gap,
        intraday=intraday,
        eligible=eligible,
    )


class TestSignals:
    def test_f1_is_negated_intraday(self):
        piv = make_pivots(3, intraday_by_symbol={"S00": -0.02, "S01": 0.03})
        sig = compute_signal(CellSpec("F1", j=0, hold=1), piv)
        assert sig.iloc[1]["S00"] == pytest.approx(0.02)
        assert sig.iloc[1]["S01"] == pytest.approx(-0.03)

    def test_f2_is_negated_trailing_return(self):
        piv = make_pivots(5)
        close = piv.close.copy()
        close.loc[close.index[3], "S00"] = 110.0  # +10% over any J ending day 3
        piv = make_pivots(5, close=close)
        sig = compute_signal(CellSpec("F2", j=3, hold=1), piv)
        assert sig.iloc[3]["S00"] == pytest.approx(-0.10)
        assert sig.iloc[3]["S01"] == pytest.approx(0.0)
        assert np.isnan(sig.iloc[2]["S00"])  # lookback incomplete

    def test_f3_skips_recent_week(self):
        n = 20
        piv = make_pivots(n)
        close = piv.close.copy()
        # S00: +50% early (inside J window), then crash in the skip week.
        close.iloc[5:, close.columns.get_loc("S00")] = 150.0
        close.iloc[n - 3 :, close.columns.get_loc("S00")] = 50.0
        piv = make_pivots(n, close=close)
        sig = compute_signal(CellSpec("F3", j=10, hold=21, skip=5), piv)
        # At the last day, the skip window hides the crash: signal uses
        # close(D-5)/close(D-15) = 150/100.
        assert sig.iloc[-1]["S00"] == pytest.approx(0.50)

    def test_orientation_top_decile_is_long_side(self):
        # F1: the biggest intraday LOSER has the HIGHEST oriented signal.
        piv = make_pivots(3, intraday_by_symbol={"S05": -0.09})
        sig = compute_signal(CellSpec("F1", j=0, hold=1), piv)
        assert sig.iloc[1]["S05"] == sig.iloc[1].max()


class TestPoolFilters:
    def test_gap_guard_window_and_threshold(self):
        n = 12
        piv = make_pivots(n)
        open_ = piv.open.copy()
        open_.iloc[4, open_.columns.get_loc("S00")] = 70.0   # -30% gap day 4
        open_.iloc[4, open_.columns.get_loc("S01")] = 80.0   # -20% gap: under guard
        # Restore flat afterwards so only day 4's gap is extreme.
        piv = make_pivots(n, open_=open_, close=pd.DataFrame(
            100.0, index=make_calendar(n), columns=piv.close.columns
        ))
        cell = CellSpec("F2", j=3, hold=1)  # guard window [D-3, D]
        excl = guard_exclusions(cell, piv)
        assert bool(excl.iloc[4]["S00"])          # day of the gap
        assert bool(excl.iloc[7]["S00"])          # still inside [D-3, D]
        assert not bool(excl.iloc[8]["S00"])      # window has passed
        assert not bool(excl.iloc[4]["S01"])      # -20% is under the 25% guard
        assert not bool(excl.iloc[3]["S00"])      # no look-ahead: day before

    def test_price_floor_and_eligibility(self):
        piv = make_pivots(4)
        close = piv.close.copy()
        close["S00"] = 4.0  # under the $5 floor
        eligible = pd.DataFrame(True, index=piv.calendar, columns=piv.close.columns)
        eligible["S01"] = False
        piv = make_pivots(4, close=close, eligible=eligible)
        cell = CellSpec("F1", j=0, hold=1)
        pool = formation_pool(cell, piv, compute_signal(cell, piv))
        assert not pool.iloc[1]["S00"]
        assert not pool.iloc[1]["S01"]
        assert pool.iloc[1]["S02"]

    def test_f1_needs_prev_close(self):
        piv = make_pivots(3)
        cell = CellSpec("F1", j=0, hold=1)
        pool = formation_pool(cell, piv, compute_signal(cell, piv))
        assert not pool.iloc[0].any()  # day 0 has no prev_rth_close
        assert pool.iloc[1].all()


class TestF1Simulation:
    def _run(self, piv):
        cell = CellSpec("F1", j=0, hold=1, primary=True)
        return simulate_cell(
            cell, piv,
            window_start=piv.calendar[0], window_end=piv.calendar[-1],
        )

    def test_overnight_return_and_cost_arithmetic(self):
        n = 4
        piv = make_pivots(n)
        # Day 1: S00/S01 are the big losers (top oriented signal).
        close = piv.close.copy()
        close.iloc[1, close.columns.get_loc("S00")] = 90.0   # -10% intraday
        close.iloc[1, close.columns.get_loc("S01")] = 92.0   # -8% intraday
        # Others get distinct mild intraday returns so ranks are unique.
        for k in range(2, N_SYMBOLS):
            close.iloc[1, k] = 100.0 + k * 0.1
        open_ = piv.open.copy()
        # Next-day opens: S00 bounces +2% vs its close, S01 +1%.
        open_.iloc[2, open_.columns.get_loc("S00")] = 90.0 * 1.02
        open_.iloc[2, open_.columns.get_loc("S01")] = 92.0 * 1.01
        bar1600 = close.copy()  # entry exactly at the 16:00 bar
        piv = make_pivots(n, close=close, open_=open_, bar1600=bar1600)
        result = self._run(piv)

        exit_date = piv.calendar[2]
        gross = result.daily_net[0][exit_date]
        assert gross == pytest.approx((0.02 + 0.01) / 2, abs=1e-12)
        c = BINDING_BP * 1e-4
        expected_net = (1 + gross) * (1 - c) ** 2 - 1
        assert result.daily_net[BINDING_BP][exit_date] == pytest.approx(
            expected_net, abs=1e-12
        )

    def test_bar1600_fallback_counted(self):
        intr = {f"S{i:02d}": -0.0005 * i for i in range(N_SYMBOLS)}
        base = make_pivots(4, intraday_by_symbol=intr)
        bar1600 = base.bar1600.copy()
        bar1600.iloc[1] = np.nan  # no 16:00 bar for anyone on day 1
        piv = make_pivots(4, intraday_by_symbol=intr, bar1600=bar1600)
        result = self._run(piv)
        assert result.counts["bar1600_fallback"] >= N_SYMBOLS

    def test_missing_exit_next_open_then_last_close(self):
        n = 10
        piv = make_pivots(n)
        open_ = piv.open.copy()
        # S00 has no rows on days 2-3 (halt): exit deferred to day 4's open.
        open_.iloc[2:4, open_.columns.get_loc("S00")] = np.nan
        piv = make_pivots(n, open_=open_)
        # Force S00 into the long decile: biggest intraday loser on day 1.
        close = piv.close.copy()
        close.iloc[1, close.columns.get_loc("S00")] = 80.0
        for k in range(1, N_SYMBOLS):
            close.iloc[1, k] = 100.0 + k * 0.1
        piv = make_pivots(n, open_=open_, close=close)
        result = self._run(piv)
        assert result.counts["exit_deferred"] >= 1

        # Now kill S00 entirely after day 1: falls back to last observed close.
        open2 = piv.open.copy()
        open2.iloc[2:, open2.columns.get_loc("S00")] = np.nan
        close2 = piv.close.copy()
        close2.iloc[2:, close2.columns.get_loc("S00")] = np.nan
        piv2 = make_pivots(n, open_=open2, close=close2)
        result2 = self._run(piv2)
        assert result2.counts["exit_last_close"] >= 1

    def test_holding_must_realize_inside_window(self):
        intr = {f"S{i:02d}": -0.0005 * i for i in range(N_SYMBOLS)}
        piv = make_pivots(5, intraday_by_symbol=intr)
        result = self._run(piv)
        # Last formation date must leave room for the D+1 exit.
        assert result.formation_dates[-1] <= piv.calendar[-2]


class TestOverlapAccounting:
    def test_f2_h2_portfolio_is_mean_of_active_tranches(self):
        """Every name +1%/day open-to-open: each tranche returns +1% daily,
        so the H=2 overlapping portfolio must also return +1% daily gross."""
        n = 12
        calendar = make_calendar(n)
        symbols = [f"S{i:02d}" for i in range(N_SYMBOLS)]
        drift = np.array([1.01**t for t in range(n)])
        open_ = pd.DataFrame(
            np.outer(drift, np.ones(N_SYMBOLS)) * 100.0,
            index=calendar, columns=symbols,
        )
        # Time-varying per-symbol close offsets so F2 signals rank uniquely,
        # while entry/exit/marking (all at opens) still drift +1%/day.
        close = open_ * (1.0 + np.outer(np.arange(n), np.linspace(0, 1e-4, N_SYMBOLS)))
        piv = make_pivots(n, open_=open_, close=close)
        cell = CellSpec("F2", j=1, hold=2)
        result = simulate_cell(
            cell, piv, window_start=calendar[0], window_end=calendar[-1]
        )
        gross = result.daily_net[0]
        # Steady state (both tranches active): exactly +1%/day.
        steady = gross.iloc[2:]
        assert np.allclose(steady.values, 0.01, atol=1e-9)

    def test_f2_costs_charged_on_entry_and_exit_days(self):
        n = 12
        calendar = make_calendar(n)
        symbols = [f"S{i:02d}" for i in range(N_SYMBOLS)]
        open_ = pd.DataFrame(100.0, index=calendar, columns=symbols)
        # Time-varying close offsets: unique F2 signals, flat open prices.
        close = open_ * (1.0 + np.outer(np.arange(n), np.linspace(0, 1e-4, N_SYMBOLS)))
        piv = make_pivots(n, open_=open_, close=close)
        cell = CellSpec("F2", j=1, hold=2)
        result = simulate_cell(
            cell, piv, window_start=calendar[0], window_end=calendar[-1]
        )
        c = BINDING_BP * 1e-4
        # Flat prices: every tranche's daily gross is 0. Each day one tranche
        # pays an entry side and one an exit side; portfolio = mean of the
        # H=2 active tranches -> daily net = ((0-c)+(0-c))/2 = -c.
        steady = result.daily_net[BINDING_BP].iloc[2:-1]
        assert np.allclose(steady.values, -c, atol=1e-9)

    def test_turnover_scales_inverse_with_hold(self):
        n = 40
        piv = make_pivots(n)
        close = piv.close * (
            1.0 + np.outer(np.arange(n), np.linspace(0, 1e-4, N_SYMBOLS))
        )
        piv = make_pivots(n, close=close)
        r2 = simulate_cell(
            CellSpec("F2", j=1, hold=2), piv,
            window_start=piv.calendar[0], window_end=piv.calendar[-1],
        )
        r5 = simulate_cell(
            CellSpec("F2", j=1, hold=5), piv,
            window_start=piv.calendar[0], window_end=piv.calendar[-1],
        )
        assert r2.turnover_daily == pytest.approx(0.5, rel=0.15)
        assert r5.turnover_daily == pytest.approx(0.2, rel=0.15)


class TestDeciles:
    def test_equal_counts_and_long_is_top(self):
        n = 4
        piv = make_pivots(n)
        close = piv.close.copy()
        # Unique intraday returns: S00 the biggest loser.
        for k in range(N_SYMBOLS):
            close.iloc[1, k] = 100.0 - (N_SYMBOLS - k) * 0.5
        piv = make_pivots(n, close=close)
        cell = CellSpec("F1", j=0, hold=1)
        result = simulate_cell(
            cell, piv, window_start=piv.calendar[0], window_end=piv.calendar[-1]
        )
        # 20 names, 10 deciles -> decile means over 2 names each; monotone
        # decreasing gross overnight return is not asserted (prices flat),
        # but the decile structure must exist.
        assert result.decile_means is not None
        assert len(result.decile_means) == 10


class TestStats:
    def test_nw_lag0_matches_plain_t(self):
        rng = pd.Series(np.sin(np.arange(50)) * 0.1 + 0.02)
        n = len(rng)
        plain = rng.mean() / (rng.std(ddof=0) / np.sqrt(n))
        assert nw_tstat(rng, 0) == pytest.approx(plain, rel=1e-9)

    def test_nw_positive_autocorr_shrinks_t(self):
        base = pd.Series(np.repeat([0.05, 0.04, 0.06, 0.05, 0.045], 10))
        assert abs(nw_tstat(base, 4)) < abs(nw_tstat(base, 0))


class TestAdvanceRule:
    def _result_with(self, daily_net_5bp, gross, bench, ic):
        cell = CellSpec("F1", j=0, hold=1, primary=True)
        r = CellResult(cell=cell)
        r.daily_net = {BINDING_BP: daily_net_5bp, 0: gross}
        r.bench_daily = bench
        r.ic_by_date = ic
        r.formation_dates = list(daily_net_5bp.index)
        return r

    def _calendar_full_is(self):
        return pd.bdate_range(IS_QUARTERS[0][0], IS_QUARTERS[-1][1])

    def test_all_four_pass_advances(self):
        cal = self._calendar_full_is()
        days = cal[:-1]
        net = pd.Series(0.001, index=days)
        gross = pd.Series(0.0015, index=days)
        bench = pd.Series(0.0002, index=days)
        ic = pd.Series(0.05 + 0.01 * np.sin(np.arange(len(days))), index=days)
        v = evaluate_advance(self._result_with(net, gross, bench, ic), cal)
        assert v.net_viability and v.selection and v.consistency and v.signal_sanity
        assert v.advance

    def test_negative_net_kills(self):
        cal = self._calendar_full_is()
        days = cal[:-1]
        net = pd.Series(-0.0005, index=days)
        gross = pd.Series(0.0015, index=days)
        bench = pd.Series(0.0002, index=days)
        ic = pd.Series(0.05, index=days)
        v = evaluate_advance(self._result_with(net, gross, bench, ic), cal)
        assert not v.net_viability
        assert not v.advance

    def test_beta_only_gross_below_benchmark_kills(self):
        cal = self._calendar_full_is()
        days = cal[:-1]
        net = pd.Series(0.001, index=days)
        gross = pd.Series(0.0015, index=days)
        bench = pd.Series(0.0030, index=days)  # universe beat the decile
        ic = pd.Series(0.05, index=days)
        v = evaluate_advance(self._result_with(net, gross, bench, ic), cal)
        assert not v.selection
        assert not v.advance

    def test_two_bad_quarters_kill(self):
        cal = self._calendar_full_is()
        days = cal[:-1]
        net = pd.Series(0.001, index=days)
        # Make Q2 and Q3 negative.
        for qs, qe in IS_QUARTERS[1:3]:
            net[(net.index >= qs) & (net.index < qe)] = -0.002
        gross = net + 0.0005
        bench = pd.Series(0.0001, index=days)
        ic = pd.Series(0.05, index=days)
        v = evaluate_advance(self._result_with(net, gross, bench, ic), cal)
        assert not v.consistency
        assert not v.advance

    def test_too_few_available_quarters_kills(self):
        cal = self._calendar_full_is()
        # Signals only in the last quarter -> n_available < 2 -> kill.
        qs, qe = IS_QUARTERS[3]
        days = cal[(cal >= qs) & (cal < qe)]
        net = pd.Series(0.001, index=days)
        gross = pd.Series(0.0015, index=days)
        bench = pd.Series(0.0002, index=days)
        ic = pd.Series(0.05, index=days)
        v = evaluate_advance(self._result_with(net, gross, bench, ic), cal)
        assert v.n_quarters_available == 1
        assert not v.consistency

    def test_weak_ic_kills(self):
        cal = self._calendar_full_is()
        days = cal[:-1]
        net = pd.Series(0.001, index=days)
        gross = pd.Series(0.0015, index=days)
        bench = pd.Series(0.0002, index=days)
        ic = pd.Series(
            np.where(np.arange(len(days)) % 2 == 0, 0.2, -0.199), index=days
        )  # mean ~ 0, t ~ 0
        v = evaluate_advance(self._result_with(net, gross, bench, ic), cal)
        assert not v.signal_sanity
        assert not v.advance


class TestNoLookahead:
    def test_future_price_change_does_not_alter_formation(self):
        n = 10
        piv = make_pivots(n)
        close = piv.close.copy()
        for k in range(N_SYMBOLS):
            close.iloc[1, k] = 100.0 - (N_SYMBOLS - k) * 0.5
        piv_a = make_pivots(n, close=close)
        close_b = close.copy()
        close_b.iloc[7:] = close_b.iloc[7:] * 1.5  # future shock
        piv_b = make_pivots(n, close=close_b)
        cell = CellSpec("F1", j=0, hold=1)
        ra = simulate_cell(cell, piv_a, piv_a.calendar[0], piv_a.calendar[4])
        rb = simulate_cell(cell, piv_b, piv_b.calendar[0], piv_b.calendar[4])
        assert ra.formation_dates == rb.formation_dates
        pd.testing.assert_series_equal(ra.ic_by_date, rb.ic_by_date)
        pd.testing.assert_series_equal(ra.daily_net[0], rb.daily_net[0])


class TestGrid:
    def test_preregistered_grid_shape(self):
        cells = preregistered_cells()
        assert len(cells) == 12
        primaries = [c for c in cells if c.primary]
        assert [c.cell_id for c in primaries] == ["F1", "F2_J5_H5", "F3_J63"]

    def test_quarter_availability_fraction(self):
        cell = CellSpec("F1", j=0, hold=1, primary=True)
        r = CellResult(cell=cell)
        cal = pd.bdate_range(IS_QUARTERS[0][0], IS_QUARTERS[-1][1])
        qs, qe = IS_QUARTERS[0]
        q_days = cal[(cal >= qs) & (cal < qe)]
        # Signals on just over 2/3 of Q1's days -> available.
        n_sig = int(np.ceil(len(q_days) * 2 / 3))
        r.formation_dates = list(q_days[:n_sig])
        r.daily_net = {BINDING_BP: pd.Series(0.001, index=q_days)}
        rows = quarterly_table(r, cal)
        assert rows[0].available
        assert not rows[1].available
