"""Unit tests for axtrade.research.universe."""

import re

import pandas as pd
import pytest

from axtrade.research.universe import compute_eligibility, hygiene_report, survivorship_summary


def _calendar(n: int, start: str = "2025-01-02") -> pd.DatetimeIndex:
    return pd.DatetimeIndex(pd.date_range(start, periods=n, freq="D"))


def _daily_dv(symbol: str, dates: pd.DatetimeIndex, dv_values: list[float]) -> pd.DataFrame:
    """Build a minimal daily frame (symbol, date, rth_dollar_volume)."""
    return pd.DataFrame(
        {
            "symbol": symbol,
            "date": dates,
            "rth_dollar_volume": dv_values,
        }
    )


def _elig_flag(elig: pd.DataFrame, symbol: str, date: pd.Timestamp) -> bool:
    row = elig[(elig["symbol"] == symbol) & (elig["date"] == date)]
    assert len(row) == 1, f"expected exactly one row for {symbol}/{date}"
    return bool(row.iloc[0]["eligible"])


class TestEligibilityDollarVolumeFloor:
    """(a) A symbol below the dollar-volume floor is never eligible."""

    def test_below_floor_never_eligible(self) -> None:
        cal = _calendar(15)
        daily = _daily_dv("LOW", cal, [1_000.0] * 15)  # always below floor

        elig = compute_eligibility(
            daily, cal, window=10, min_days=3, min_coverage=0.90,
            min_dollar_volume=5_000.0,
        )

        assert not elig["eligible"].any()


class TestEligibilityCoverageRule:
    """(b) Missing >10% of the trailing window makes a symbol ineligible."""

    def test_coverage_breach_within_window(self) -> None:
        cal = _calendar(20)
        # Present every day except indices 8 and 9 (both fall inside the
        # trailing window=10 ending at index 15).
        present_mask = [i not in (8, 9) for i in range(20)]
        dates_present = cal[present_mask]
        dv_present = [1_000_000.0] * len(dates_present)
        daily = _daily_dv("MID", dates_present, dv_present)

        elig = compute_eligibility(
            daily, cal, window=10, min_days=3, min_coverage=0.90,
            min_dollar_volume=5_000.0,
        )

        # Window ending at index 15 = indices 6..15 (10 days); 8 and 9
        # missing => coverage 0.8 < 0.90 => ineligible.
        assert _elig_flag(elig, "MID", cal[15]) is False

        # Window ending at index 5 (indices 0..5) never touches 8/9 =>
        # full coverage, high dv, elapsed=6 >= min_days=3 => eligible.
        assert _elig_flag(elig, "MID", cal[5]) is True


class TestEligibilityWarmup:
    """(c) No eligibility before min_days of history has elapsed."""

    def test_no_eligibility_before_min_days(self) -> None:
        cal = _calendar(10)
        daily = _daily_dv("NEW", cal, [1_000_000.0] * 10)  # full coverage, high dv

        elig = compute_eligibility(
            daily, cal, window=10, min_days=5, min_coverage=0.90,
            min_dollar_volume=5_000.0,
        )

        # elapsed = i+1 (idx0=0); elapsed < 5 for i in 0..3.
        for i in range(4):
            assert _elig_flag(elig, "NEW", cal[i]) is False, f"index {i}"

        # elapsed == 5 at i=4 => warmup satisfied, coverage/dv both pass.
        assert _elig_flag(elig, "NEW", cal[4]) is True


class TestEligibilityNoLookAhead:
    """(d) Making a symbol liquid ONLY on day D must not change eligibility
    on any date < D."""

    def test_future_liquidity_spike_does_not_affect_past(self) -> None:
        cal = _calendar(20)
        spike_idx = 10

        baseline_dv = [1_000.0] * 20  # always below floor
        spiked_dv = list(baseline_dv)
        spiked_dv[spike_idx] = 1_000_000_000.0  # huge spike, day D only

        daily_baseline = _daily_dv("SYM", cal, baseline_dv)
        daily_spiked = _daily_dv("SYM", cal, spiked_dv)

        common_kwargs = dict(
            window=10, min_days=3, min_coverage=0.90, min_dollar_volume=5_000.0
        )
        elig_baseline = compute_eligibility(daily_baseline, cal, **common_kwargs)
        elig_spiked = compute_eligibility(daily_spiked, cal, **common_kwargs)

        for i in range(spike_idx):
            base_flag = _elig_flag(elig_baseline, "SYM", cal[i])
            spiked_flag = _elig_flag(elig_spiked, "SYM", cal[i])
            assert base_flag == spiked_flag, f"index {i} diverged"


class TestEligibilityExcludedBenchmark:
    """(e) An excluded symbol (e.g. benchmark ETF) is never eligible."""

    def test_excluded_symbol_never_eligible(self) -> None:
        cal = _calendar(15)
        daily = _daily_dv("SPY", cal, [1_000_000_000.0] * 15)  # trivially liquid

        elig = compute_eligibility(
            daily, cal, window=10, min_days=3, min_coverage=0.90,
            min_dollar_volume=5_000.0, exclude={"SPY"},
        )

        assert not elig["eligible"].any()


class TestSurvivorshipSummary:
    """(9) Two-symbol toy universe with constant returns."""

    def test_ew_and_benchmark_match_hand_computed_compound(self) -> None:
        cal = _calendar(6)
        n_used = len(cal) - 1  # first date has no prior-day eligibility

        rows = []
        for date in cal[1:]:
            rows.append({"symbol": "A", "date": date, "cc_ret": 0.01})
            rows.append({"symbol": "B", "date": date, "cc_ret": 0.02})
            rows.append({"symbol": "SPY", "date": date, "cc_ret": 0.005})
        # First date: NaN cc_ret (no prior close), still present as rows.
        rows.append({"symbol": "A", "date": cal[0], "cc_ret": float("nan")})
        rows.append({"symbol": "B", "date": cal[0], "cc_ret": float("nan")})
        rows.append({"symbol": "SPY", "date": cal[0], "cc_ret": float("nan")})
        daily = pd.DataFrame(rows)

        elig_rows = []
        for date in cal:
            elig_rows.append({
                "symbol": "A", "date": date, "coverage": 1.0,
                "med_dollar_volume": 1e7, "eligible": True,
            })
            elig_rows.append({
                "symbol": "B", "date": date, "coverage": 1.0,
                "med_dollar_volume": 1e7, "eligible": True,
            })
        eligibility = pd.DataFrame(elig_rows)

        report = survivorship_summary(daily, eligibility, cal, benchmark_symbol="SPY")

        ew_expected = (1.015) ** n_used - 1  # mean(0.01, 0.02) = 0.015
        bench_expected = (1.005) ** n_used - 1

        ew_match = re.search(r"EW eligible-universe total return: ([\-\d\.]+)%", report)
        bench_match = re.search(r"Benchmark \(SPY\) total return: ([\-\d\.]+)%", report)
        assert ew_match is not None
        assert bench_match is not None

        ew_reported = float(ew_match.group(1)) / 100.0
        bench_reported = float(bench_match.group(1)) / 100.0

        assert ew_reported == pytest.approx(ew_expected, abs=1e-5)
        assert bench_reported == pytest.approx(bench_expected, abs=1e-5)


class TestHygieneReportExtremeMoves:
    """Regression test: the extreme-moves listing must only flag rows that
    actually breach |cc_ret| > 0.5, and its count must match the listing
    (caught a reindex-alignment bug during the phase-6A smoke run, where
    every row got flagged with garbage NaT/NaN values)."""

    def test_extreme_moves_count_matches_filter(self) -> None:
        cal = pd.DatetimeIndex(pd.date_range("2025-01-02", periods=5, freq="D"))
        daily = pd.DataFrame(
            [
                {
                    "symbol": "AAA", "date": cal[0], "first_bar_min": 570,
                    "last_bar_min": 959, "rth_volume": 100, "rth_dollar_volume": 1e6,
                    "bar1600_close": 1.0, "cc_ret": float("nan"),
                },
                {
                    "symbol": "AAA", "date": cal[1], "first_bar_min": 570,
                    "last_bar_min": 959, "rth_volume": 100, "rth_dollar_volume": 1e6,
                    "bar1600_close": 1.0, "cc_ret": 0.01,
                },
                {
                    "symbol": "AAA", "date": cal[2], "first_bar_min": 570,
                    "last_bar_min": 959, "rth_volume": 100, "rth_dollar_volume": 1e6,
                    "bar1600_close": 1.0, "cc_ret": 0.60,  # extreme
                },
                {
                    "symbol": "AAA", "date": cal[3], "first_bar_min": 570,
                    "last_bar_min": 959, "rth_volume": 100, "rth_dollar_volume": 1e6,
                    "bar1600_close": 1.0, "cc_ret": -0.02,
                },
                {
                    "symbol": "AAA", "date": cal[4], "first_bar_min": 570,
                    "last_bar_min": 959, "rth_volume": 100, "rth_dollar_volume": 1e6,
                    "bar1600_close": 1.0, "cc_ret": -0.55,  # extreme
                },
            ]
        )
        eligibility = pd.DataFrame(
            {"symbol": [], "date": [], "coverage": [], "med_dollar_volume": [], "eligible": []}
        )

        report = hygiene_report(daily, cal, eligibility, exclude=set())

        assert "Extreme moves (|cc_ret| > 0.5): 2" in report
        assert "NaT" not in report
        assert "AAA 2025-01-04: 0.6000" in report
        assert "AAA 2025-01-06: -0.5500" in report
