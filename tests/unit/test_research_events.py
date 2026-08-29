"""Tests for axtrade.research.events (E4 tier-1 calendar loader)."""

import pandas as pd
import pytest

from axtrade.research.events import (
    EVENT_TIMES_ET,
    coverage,
    event_dates,
    load_event_calendar,
)


@pytest.fixture
def calendar_path(tmp_path):
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2024-01-31", "2024-03-20", "2024-03-15", "2024-02-13", "2020-03-15"]
            ),
            "event": ["fomc", "fomc", "nfp", "cpi", "fomc"],
            "scheduled": [True, True, True, True, False],
            "source": ["s"] * 5,
        }
    )
    path = tmp_path / "cal.parquet"
    df.to_parquet(path, index=False)
    return path


def test_load_and_filter(calendar_path):
    cal = load_event_calendar(calendar_path)
    assert len(cal) == 5
    fomc = event_dates(cal, "fomc")
    assert list(fomc) == list(pd.to_datetime(["2024-01-31", "2024-03-20"]))
    all_fomc = event_dates(cal, "fomc", scheduled_only=False)
    assert len(all_fomc) == 3
    assert all_fomc.is_monotonic_increasing


def test_coverage_and_times(calendar_path):
    cal = load_event_calendar(calendar_path)
    first, last = coverage(cal, "fomc")
    assert first == pd.Timestamp("2020-03-15")
    assert last == pd.Timestamp("2024-03-20")
    assert EVENT_TIMES_ET["cpi"] == "08:30"


def test_unknown_event_rejected(calendar_path):
    cal = load_event_calendar(calendar_path)
    with pytest.raises(ValueError):
        event_dates(cal, "gdp")


def test_bad_calendar_rejected(tmp_path):
    path = tmp_path / "bad.parquet"
    pd.DataFrame({"date": pd.to_datetime(["2024-01-01"]), "event": ["mystery"],
                  "scheduled": [True]}).to_parquet(path, index=False)
    with pytest.raises(ValueError, match="unknown event"):
        load_event_calendar(path)
