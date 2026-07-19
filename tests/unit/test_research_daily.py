"""Unit tests for axtrade.research.daily."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from axtrade.research.daily import build_symbol_daily, trading_calendar

_ET = ZoneInfo("America/New_York")
_UTC = ZoneInfo("UTC")


def _et_to_utc_naive(date_str: str, time_str: str) -> pd.Timestamp:
    """Build a naive-UTC Timestamp from an ET wall-clock date/time.

    Uses zoneinfo directly (not the implementation's own tz_convert path)
    so this is an independent check of the ET conversion under test.
    """
    dt_et = datetime.fromisoformat(f"{date_str}T{time_str}").replace(tzinfo=_ET)
    dt_utc = dt_et.astimezone(_UTC).replace(tzinfo=None)
    return pd.Timestamp(dt_utc)


def _bar(date_str: str, time_str: str, *, o: float, h: float, l: float, c: float, v: int) -> dict:
    return {
        "timestamp": _et_to_utc_naive(date_str, time_str),
        "open": o,
        "high": h,
        "low": l,
        "close": c,
        "volume": v,
    }


def _df(bars: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(bars)


class TestDSTCorrectness:
    """DST handling: RTH boundary must track ET wall-clock, not fixed UTC offset."""

    def test_august_1330_utc_is_rth(self) -> None:
        # 13:30 UTC in August = 09:30 EDT (UTC-4) -- exactly RTH open.
        df = pd.DataFrame(
            [{
                "timestamp": pd.Timestamp("2025-08-01 13:30:00"),
                "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.2, "volume": 100,
            }]
        )
        daily = build_symbol_daily(df, "TST")
        assert len(daily) == 1
        assert daily.iloc[0]["first_bar_min"] == 570

    def test_january_1330_utc_is_not_rth(self) -> None:
        # 13:30 UTC in January = 08:30 EST (UTC-5) -- before RTH open.
        df = pd.DataFrame(
            [{
                "timestamp": pd.Timestamp("2025-01-02 13:30:00"),
                "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.2, "volume": 100,
            }]
        )
        daily = build_symbol_daily(df, "TST")
        assert daily.empty

    def test_january_1430_utc_is_rth(self) -> None:
        # 14:30 UTC in January = 09:30 EST -- RTH open.
        df = pd.DataFrame(
            [{
                "timestamp": pd.Timestamp("2025-01-02 14:30:00"),
                "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.2, "volume": 100,
            }]
        )
        daily = build_symbol_daily(df, "TST")
        assert len(daily) == 1
        assert daily.iloc[0]["first_bar_min"] == 570


class TestRTHFields:
    """RTH-only OHLCV aggregation, pre/post-market exclusion."""

    def _hand_built_day(self) -> pd.DataFrame:
        bars = [
            _bar("2025-06-02", "08:00:00", o=99.0, h=99.5, l=98.5, c=99.2, v=1000),  # pre-market
            _bar("2025-06-02", "09:30:00", o=100.0, h=101.0, l=99.5, c=100.5, v=500),  # RTH open
            _bar("2025-06-02", "12:00:00", o=100.5, h=102.0, l=99.0, c=101.0, v=300),  # RTH mid
            _bar("2025-06-02", "15:59:00", o=101.0, h=101.5, l=100.8, c=101.2, v=400),  # RTH close
            _bar("2025-06-02", "16:30:00", o=101.2, h=101.3, l=101.0, c=101.1, v=800),  # post-market
        ]
        return _df(bars)

    def test_rth_fields_exact(self) -> None:
        daily = build_symbol_daily(self._hand_built_day(), "TST")
        assert len(daily) == 1
        row = daily.iloc[0]

        assert row["rth_open"] == pytest.approx(100.0)
        assert row["rth_close"] == pytest.approx(101.2)
        assert row["rth_high"] == pytest.approx(102.0)
        assert row["rth_low"] == pytest.approx(99.0)
        assert row["rth_volume"] == 500 + 300 + 400
        expected_dollar = 100.5 * 500 + 101.0 * 300 + 101.2 * 400
        assert row["rth_dollar_volume"] == pytest.approx(expected_dollar)
        assert row["rth_bar_count"] == 3
        assert row["first_bar_min"] == 570  # 09:30
        assert row["last_bar_min"] == 959  # 15:59

    def test_pre_and_post_market_excluded_but_counted_in_ext_volume(self) -> None:
        daily = build_symbol_daily(self._hand_built_day(), "TST")
        row = daily.iloc[0]
        # pre-market 1000 + post-market 800
        assert row["ext_volume"] == 1000 + 800


class Test1600Bar:
    """bar1600_close captures the closing-auction proxy bar."""

    def test_bar1600_present(self) -> None:
        bars = [
            _bar("2025-06-02", "09:30:00", o=100.0, h=101.0, l=99.5, c=100.5, v=500),
            _bar("2025-06-02", "15:59:00", o=101.0, h=101.5, l=100.8, c=101.2, v=400),
            _bar("2025-06-02", "16:00:00", o=101.2, h=101.4, l=101.1, c=101.3, v=200),
        ]
        daily = build_symbol_daily(_df(bars), "TST")
        assert daily.iloc[0]["bar1600_close"] == pytest.approx(101.3)
        # 16:00 bar volume is outside the canonical RTH window.
        assert daily.iloc[0]["ext_volume"] == 200
        assert daily.iloc[0]["rth_close"] == pytest.approx(101.2)

    def test_bar1600_absent(self) -> None:
        bars = [
            _bar("2025-06-02", "09:30:00", o=100.0, h=101.0, l=99.5, c=100.5, v=500),
            _bar("2025-06-02", "15:59:00", o=101.0, h=101.5, l=100.8, c=101.2, v=400),
        ]
        daily = build_symbol_daily(_df(bars), "TST")
        assert pd.isna(daily.iloc[0]["bar1600_close"])


class TestHalfDay:
    """Half-day sessions end at 13:00 ET (last bar starts 12:59)."""

    def test_half_day_last_bar(self) -> None:
        bars = [
            _bar("2025-11-28", "09:30:00", o=100.0, h=101.0, l=99.5, c=100.5, v=500),
            _bar("2025-11-28", "12:59:00", o=100.8, h=101.0, l=100.5, c=100.9, v=300),
        ]
        daily = build_symbol_daily(_df(bars), "TST")
        assert len(daily) == 1
        row = daily.iloc[0]
        assert row["rth_close"] == pytest.approx(100.9)
        assert row["last_bar_min"] == 779  # 12:59 -> 12*60+59


class TestNoRTHBarsDay:
    """A day with only pre-market bars produces no output row."""

    def test_only_premarket_bars(self) -> None:
        bars = [
            _bar("2025-06-02", "08:00:00", o=99.0, h=99.5, l=98.5, c=99.2, v=1000),
            _bar("2025-06-02", "09:00:00", o=99.2, h=99.6, l=99.0, c=99.4, v=500),
        ]
        daily = build_symbol_daily(_df(bars), "TST")
        assert daily.empty


class TestDerivedReturns:
    """gap_ret/cc_ret/intraday_ret across an intentionally missing day."""

    def test_missing_middle_day_uses_previous_present_row(self) -> None:
        bars = [
            _bar("2025-06-02", "09:30:00", o=100.0, h=101.0, l=99.5, c=100.0, v=500),
            _bar("2025-06-02", "15:59:00", o=100.5, h=101.0, l=100.0, c=100.0, v=400),
            # 2025-06-03 intentionally missing (no bars at all)
            _bar("2025-06-04", "09:30:00", o=102.0, h=102.5, l=101.5, c=102.0, v=500),
            _bar("2025-06-04", "15:59:00", o=102.5, h=103.0, l=102.0, c=103.0, v=400),
        ]
        daily = build_symbol_daily(_df(bars), "TST")
        assert len(daily) == 2  # missing day produces no row

        first, second = daily.iloc[0], daily.iloc[1]

        # First row: no prior row at all.
        assert pd.isna(first["prev_rth_close"])
        assert pd.isna(first["gap_ret"])
        assert pd.isna(first["cc_ret"])
        assert first["intraday_ret"] == pytest.approx(100.0 / 100.0 - 1)

        # Second row: prev close is the previous PRESENT row (06-02's close
        # of 100.0), even though a day is missing in between.
        assert second["prev_rth_close"] == pytest.approx(100.0)
        assert second["gap_ret"] == pytest.approx(102.0 / 100.0 - 1)
        assert second["cc_ret"] == pytest.approx(103.0 / 100.0 - 1)
        assert second["intraday_ret"] == pytest.approx(103.0 / 102.0 - 1)


class TestTradingCalendar:
    """trading_calendar drops dates with too few symbols present."""

    def test_drops_date_below_min_frac(self) -> None:
        daily = pd.DataFrame(
            [
                {"symbol": "AAA", "date": pd.Timestamp("2025-06-02")},
                {"symbol": "BBB", "date": pd.Timestamp("2025-06-02")},
                {"symbol": "CCC", "date": pd.Timestamp("2025-06-02")},
                {"symbol": "AAA", "date": pd.Timestamp("2025-06-03")},
                {"symbol": "BBB", "date": pd.Timestamp("2025-06-03")},
                {"symbol": "AAA", "date": pd.Timestamp("2025-06-04")},
            ]
        )
        cal = trading_calendar(daily, min_frac=0.5)
        # 06-02: 3/3 symbols -> included
        # 06-03: 2/3 symbols -> included (>= 0.5)
        # 06-04: 1/3 symbols -> dropped (< 0.5)
        assert pd.Timestamp("2025-06-02") in cal
        assert pd.Timestamp("2025-06-03") in cal
        assert pd.Timestamp("2025-06-04") not in cal
        assert len(cal) == 2
