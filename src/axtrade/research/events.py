"""Scheduled-event calendar access for the E4 event-association study.

Tier-1 (certified) loader over the calendar built by
``scripts/research/event_study/fetch_calendars.py`` (see
``docs/event-study-plan.md``). The parquet holds one row per event with
columns ``date``, ``event`` (fomc|cpi|nfp), ``scheduled`` (bool), ``source``.

Official release times (ET), for intraday alignment in Phase 2:
FOMC statement 14:00 (press conference 14:30); CPI and the Employment
Situation (NFP) 08:30 — i.e. pre-open, so the reaction day is the release
date itself, starting at the open.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

EVENT_TIMES_ET: dict[str, str] = {"fomc": "14:00", "cpi": "08:30", "nfp": "08:30"}

DEFAULT_CALENDAR_PATH = Path("data/research/event_study/event_calendar.parquet")

_VALID_EVENTS = frozenset(EVENT_TIMES_ET)


def load_event_calendar(path: Path | str = DEFAULT_CALENDAR_PATH) -> pd.DataFrame:
    """Load the event calendar; raises FileNotFoundError if not yet built."""
    df = pd.read_parquet(path)
    missing = {"date", "event", "scheduled"} - set(df.columns)
    if missing:
        raise ValueError(f"event calendar missing columns: {sorted(missing)}")
    bad = set(df["event"].unique()) - _VALID_EVENTS
    if bad:
        raise ValueError(f"unknown event types in calendar: {sorted(bad)}")
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    return df


def event_dates(
    calendar: pd.DataFrame,
    event: str,
    *,
    scheduled_only: bool = True,
) -> pd.DatetimeIndex:
    """Dates for one event type, sorted, deduplicated."""
    if event not in _VALID_EVENTS:
        raise ValueError(f"unknown event {event!r}; expected one of {sorted(_VALID_EVENTS)}")
    sel = calendar[calendar["event"] == event]
    if scheduled_only:
        sel = sel[sel["scheduled"]]
    return pd.DatetimeIndex(sel["date"].sort_values().unique())


def coverage(calendar: pd.DataFrame, event: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """First and last date the calendar covers for an event type.

    Analyses must restrict themselves to this window: outside it, absence of
    an event row means "not covered", not "no event".
    """
    dates = event_dates(calendar, event, scheduled_only=False)
    if len(dates) == 0:
        raise ValueError(f"no rows for event {event!r}")
    return dates[0], dates[-1]
