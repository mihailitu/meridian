"""E4 Phase 1: build the scheduled-event calendar (FOMC / CPI / NFP).

Tier-2 scratch script (docs/event-study-plan.md). Sources are official
publications whose URLs/filenames carry the event date:

  FOMC  federalreserve.gov: current calendars page + historical year pages;
        decision dates parsed from minutes/statement links
        (fomcminutes<YYYYMMDD>, /fomc/minutes/<YYYYMMDD>.htm,
        monetary<YYYYMMDD>a). Minutes are stamped with the meeting's final
        (decision) day.
  CPI   bls.gov/bls/news-release/cpi.htm    -> cpi_<MMDDYYYY>.htm
  NFP   bls.gov/bls/news-release/empsit.htm -> empsit_<MMDDYYYY>.htm
        (BLS blocks non-browser clients; the listing pages are fetched via
        their Wayback snapshots, but the filenames parsed are BLS's own
        date-stamped release files, so the timestamps are official.)

Output: data/research/event_study/event_calendar.parquet
        columns: date (datetime64), event (fomc|cpi|nfp), scheduled (bool),
                 source (str)
Raw downloads are kept in data/research/event_study/raw/ for provenance.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

OUT_DIR = Path("data/research/event_study")
RAW_DIR = OUT_DIR / "raw"
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) axtrade-research"}

# Known unscheduled FOMC actions with their own date-stamped minutes or
# statements, 2000->. Curated from the Fed's historical pages; anything
# in this set is kept but flagged scheduled=False.
UNSCHEDULED_FOMC = {
    "2001-01-03", "2001-04-18", "2001-09-17",   # intermeeting cuts
    "2008-01-22", "2008-10-08",                 # crisis cuts
    "2020-03-03", "2020-03-15", "2020-03-23",   # COVID emergency actions
}

# Statement-pattern false positives: press releases with monetary<date>a URLs
# that are NOT policy-decision days, plus first-day stamps of two-day meetings.
# Verified against the Fed's meeting calendars 2026-08-29.
FOMC_DROPS = {
    "2012-10-23",  # first day of the Oct 23-24 meeting (decision = 24th)
    "2019-10-11",  # statement on Treasury-bill purchases / repo operations
    "2020-03-31",  # FIMA repo facility announcement
    "2020-08-27",  # revised longer-run-goals framework (Jackson Hole)
    "2025-08-22",  # Jackson Hole speech press release
}

FOMC_URLS = ["https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"] + [
    f"https://www.federalreserve.gov/monetarypolicy/fomchistorical{y}.htm"
    for y in range(2000, 2021)
]
FOMC_PATTERNS = [
    re.compile(r"fomcminutes(\d{8})"),
    re.compile(r"/fomc/minutes/(\d{8})\.htm"),
    re.compile(r"monetary(\d{8})a"),
]

BLS_SOURCES = {
    "cpi": ("https://web.archive.org/web/2025/https://www.bls.gov/bls/news-release/cpi.htm",
            re.compile(r"cpi_(\d{8})\.htm")),
    "nfp": ("https://web.archive.org/web/2025/https://www.bls.gov/bls/news-release/empsit.htm",
            re.compile(r"empsit_(\d{8})\.htm")),
}


def fetch(url: str, cache_name: str) -> str:
    cache = RAW_DIR / cache_name
    if cache.exists():
        return cache.read_text(errors="replace")
    resp = requests.get(url, headers=UA, timeout=60, allow_redirects=True)
    resp.raise_for_status()
    cache.write_text(resp.text)
    return resp.text


def parse_fomc() -> pd.DataFrame:
    rows = {}
    for url in FOMC_URLS:
        name = "fomc_" + url.rsplit("/", 1)[-1]
        try:
            html = fetch(url, name)
        except requests.RequestException as exc:
            print(f"WARN: {url}: {exc}", file=sys.stderr)
            continue
        for pat in FOMC_PATTERNS:
            for raw in pat.findall(html):
                try:
                    d = datetime.strptime(raw, "%Y%m%d").date()
                except ValueError:
                    continue
                if d.year >= 2000 and d.strftime("%Y-%m-%d") not in FOMC_DROPS:
                    # first source wins; historical pages are authoritative
                    rows.setdefault(d, url)
    # older pages use link formats the patterns miss; the known unscheduled
    # actions are added explicitly so Q1 can attribute those days
    for iso in UNSCHEDULED_FOMC:
        d = datetime.strptime(iso, "%Y-%m-%d").date()
        rows.setdefault(d, "curated:known-unscheduled-action")
    df = pd.DataFrame(
        {"date": pd.to_datetime(sorted(rows)), "event": "fomc",
         "source": [rows[d] for d in sorted(rows)]}
    )
    df["scheduled"] = ~df["date"].dt.strftime("%Y-%m-%d").isin(UNSCHEDULED_FOMC)
    return df


def parse_bls(event: str) -> pd.DataFrame:
    url, pat = BLS_SOURCES[event]
    html = fetch(url, f"{event}_archive.html")
    dates = set()
    for raw in pat.findall(html):
        try:
            dates.add(datetime.strptime(raw, "%m%d%Y").date())
        except ValueError:
            continue
    return pd.DataFrame(
        {"date": pd.to_datetime(sorted(dates)), "event": event,
         "scheduled": True, "source": url}
    )


def main() -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    frames = [parse_fomc(), parse_bls("cpi"), parse_bls("nfp")]
    cal = pd.concat(frames, ignore_index=True)[
        ["date", "event", "scheduled", "source"]
    ].sort_values(["date", "event"]).reset_index(drop=True)

    out = OUT_DIR / "event_calendar.parquet"
    cal.to_parquet(out, index=False)

    print(f"wrote {out}: {len(cal)} rows")
    for ev, g in cal.groupby("event"):
        print(f"  {ev}: {len(g)} events, {g['date'].min().date()} -> "
              f"{g['date'].max().date()}, unscheduled={int((~g['scheduled']).sum())}")
    fomc = cal[cal["event"] == "fomc"]
    counts = fomc[fomc["scheduled"]].groupby(fomc["date"].dt.year).size()
    odd = counts[(counts != 8) & (counts.index < counts.index.max())]
    if len(odd):
        print("REVIEW: scheduled-FOMC years without exactly 8 meetings:")
        print(odd.to_string())
        for y in odd.index:
            days = fomc[fomc["date"].dt.year == y]["date"].dt.strftime("%Y-%m-%d")
            print(f"  {y}: {', '.join(days)}")


if __name__ == "__main__":
    main()
