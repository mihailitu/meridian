"""E4 Phase 2: build the per-symbol earnings calendar with BMO/AMC session tags.

Tier-2 scratch script (docs/event-study-plan.md §3, §4a). Primary source is
the Nasdaq earnings-calendar API, queried once per trading day:

  GET https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD

It 403s or hangs without browser-like headers, so a real User-Agent /
Accept / Accept-Language set is sent on every request. The "time" field on
each row ("time-pre-market" / "time-after-hours" / "time-not-supplied") maps
to session bmo/amc/unknown.

A random 60-symbol sample (seed 42) is cross-checked against yfinance's
`get_earnings_dates()` as an independent source, per the §3 gate (20-name
manual spot-check >=95% correct decides whether session tags may be used).

Output: data/research/event_study/earnings_calendar.parquet
        columns: symbol (str), date (datetime64), session (bmo|amc|unknown),
                 source (str, "nasdaq")
        data/research/event_study/earnings_crosscheck.csv
        columns: symbol, nasdaq_date, nasdaq_session, yf_date, yf_session,
                 date_match, session_match
Raw per-day JSON is cached in data/research/event_study/raw_nasdaq/ for
provenance and to make reruns free.
"""

from __future__ import annotations

import json
import random
import sys
import time
from datetime import date as date_cls
from datetime import datetime, time as time_cls

import pandas as pd
import requests
import yfinance as yf
from pathlib import Path

OUT_DIR = Path("data/research/event_study")
RAW_DIR = OUT_DIR / "raw_nasdaq"
HISTORICAL_DIR = Path("data/historical")
CALENDAR_TXT = Path("data/daily/calendar.txt")
DAILY_BARS = Path("data/daily/daily_bars.parquet")

CALENDAR_URL = "https://api.nasdaq.com/api/calendar/earnings?date={date}"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT_S = 10
RATE_LIMIT_S = 0.4
CONSECUTIVE_403_LIMIT = 5

SESSION_MAP = {
    "time-pre-market": "bmo",
    "time-after-hours": "amc",
    "time-not-supplied": "unknown",
}

WINDOW_START = date_cls(2024, 8, 1)
WINDOW_END = date_cls(2026, 2, 1)
CROSSCHECK_N = 60
CROSSCHECK_SEED = 42
ET_OPEN = time_cls(9, 30)
ET_CLOSE = time_cls(16, 0)


class NasdaqBlocked(RuntimeError):
    pass


def archive_symbols() -> set[str]:
    return {
        p.name.split("_1m_")[0]
        for p in HISTORICAL_DIR.glob("*_1m_2024-08-01_2026-02-01.parquet")
    }


def trading_days() -> list[str]:
    if CALENDAR_TXT.exists():
        lines = [ln.strip() for ln in CALENDAR_TXT.read_text().splitlines() if ln.strip()]
        try:
            days = sorted({datetime.strptime(ln, "%Y-%m-%d").date() for ln in lines})
        except ValueError:
            days = None
        if days:
            return [d.strftime("%Y-%m-%d") for d in days if WINDOW_START <= d <= WINDOW_END]
    df = pd.read_parquet(DAILY_BARS, columns=["date"])
    days = sorted(pd.to_datetime(df["date"]).dt.date.unique())
    return [d.strftime("%Y-%m-%d") for d in days if WINDOW_START <= d <= WINDOW_END]


def fetch_day(session: requests.Session, day: str) -> tuple[dict, bool]:
    cache = RAW_DIR / f"{day}.json"
    if cache.exists():
        return json.loads(cache.read_text()), True
    resp = session.get(CALENDAR_URL.format(date=day), headers=HEADERS, timeout=TIMEOUT_S)
    if resp.status_code == 403:
        raise NasdaqBlocked(f"403 for {day}")
    resp.raise_for_status()
    data = resp.json()
    cache.write_text(json.dumps(data))
    return data, False


def build_calendar(days: list[str]) -> tuple[pd.DataFrame, dict]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    rows: list[dict] = []
    stats = {"fetched": 0, "cached": 0, "warned_days": 0, "empty_days": 0}
    consecutive_403 = 0

    for day in days:
        try:
            data, was_cached = fetch_day(session, day)
        except NasdaqBlocked as exc:
            consecutive_403 += 1
            stats["warned_days"] += 1
            print(f"WARN: {exc} ({consecutive_403} consecutive 403s)", file=sys.stderr)
            if consecutive_403 >= CONSECUTIVE_403_LIMIT:
                print(
                    "ERROR: Nasdaq earnings API returned 403 on "
                    f"{CONSECUTIVE_403_LIMIT} consecutive distinct days despite "
                    "browser-like headers -- it appears blocked. Stopping per "
                    "spec; not attempting proxies or scraping workarounds.",
                    file=sys.stderr,
                )
                sys.exit(1)
            continue
        except requests.RequestException as exc:
            stats["warned_days"] += 1
            print(f"WARN: {day}: {exc}", file=sys.stderr)
            continue

        consecutive_403 = 0
        if was_cached:
            stats["cached"] += 1
        else:
            stats["fetched"] += 1
            time.sleep(RATE_LIMIT_S)

        day_rows = ((data or {}).get("data") or {}).get("rows") or []
        if not day_rows:
            stats["empty_days"] += 1
        for r in day_rows:
            sym = (r.get("symbol") or "").strip()
            if not sym:
                continue
            rows.append(
                {
                    "symbol": sym,
                    "date": day,
                    "session": SESSION_MAP.get(r.get("time"), "unknown"),
                }
            )

    raw_df = pd.DataFrame(rows)
    if raw_df.empty:
        raw_df = pd.DataFrame(columns=["symbol", "date", "session"])
    raw_df = raw_df.drop_duplicates(subset=["symbol", "date"])
    return raw_df, stats


def yf_session(ts: pd.Timestamp) -> str | None:
    """Map a tz-aware yfinance earnings timestamp to bmo/amc, or None if unusable."""
    t = ts.time()
    if t == time_cls(0, 0):
        return None  # midnight-only stamp: no real time info
    if t < ET_OPEN:
        return "bmo"
    if t >= ET_CLOSE:
        return "amc"
    return "unknown"


def match_dates(
    nasdaq_dates: list[date_cls], yf_dates: list[date_cls]
) -> list[tuple[date_cls | None, date_cls | None]]:
    """Greedy nearest-date pairing within +/-1 calendar day, each date used once."""
    nq = sorted(nasdaq_dates)
    yq = sorted(yf_dates)
    used_yf: set[int] = set()
    pairs: list[tuple[date_cls | None, date_cls | None]] = []
    for nd in nq:
        best_i, best_diff = None, None
        for i, yd in enumerate(yq):
            if i in used_yf:
                continue
            diff = abs((yd - nd).days)
            if diff <= 1 and (best_diff is None or diff < best_diff):
                best_i, best_diff = i, diff
        if best_i is not None:
            used_yf.add(best_i)
            pairs.append((nd, yq[best_i]))
        else:
            pairs.append((nd, None))
    for i, yd in enumerate(yq):
        if i not in used_yf:
            pairs.append((None, yd))
    return pairs


def crosscheck(cal: pd.DataFrame) -> pd.DataFrame:
    symbols = sorted(cal["symbol"].unique())
    rng = random.Random(CROSSCHECK_SEED)
    sample = rng.sample(symbols, min(CROSSCHECK_N, len(symbols)))

    out_rows = []
    for sym in sample:
        nasdaq_sub = cal[cal["symbol"] == sym]
        nasdaq_session_by_date = dict(zip(nasdaq_sub["date"].dt.date, nasdaq_sub["session"]))
        nasdaq_dates = list(nasdaq_session_by_date.keys())

        try:
            yf_df = yf.Ticker(sym).get_earnings_dates(limit=12)
        except Exception as exc:  # yfinance can raise a variety of errors
            print(f"WARN: yfinance failed for {sym}: {exc}", file=sys.stderr)
            yf_df = None

        yf_session_by_date: dict[date_cls, str | None] = {}
        if yf_df is not None and not yf_df.empty:
            for ts in yf_df.index:
                d = ts.date()
                if WINDOW_START <= d <= WINDOW_END:
                    yf_session_by_date[d] = yf_session(ts)
        yf_dates = list(yf_session_by_date.keys())

        for nd, yd in match_dates(nasdaq_dates, yf_dates):
            nasdaq_session = nasdaq_session_by_date.get(nd) if nd else None
            yfd_session = yf_session_by_date.get(yd) if yd else None
            date_match = nd is not None and yd is not None
            session_match = None
            if date_match and yfd_session is not None:
                session_match = nasdaq_session == yfd_session
            out_rows.append(
                {
                    "symbol": sym,
                    "nasdaq_date": nd,
                    "nasdaq_session": nasdaq_session,
                    "yf_date": yd,
                    "yf_session": yfd_session,
                    "date_match": date_match,
                    "session_match": session_match,
                }
            )

    return pd.DataFrame(
        out_rows,
        columns=[
            "symbol",
            "nasdaq_date",
            "nasdaq_session",
            "yf_date",
            "yf_session",
            "date_match",
            "session_match",
        ],
    )


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    archive = archive_symbols()
    days = trading_days()

    raw_df, stats = build_calendar(days)

    filtered = raw_df[raw_df["symbol"].isin(archive)].copy()
    filtered["date"] = pd.to_datetime(filtered["date"])
    filtered["source"] = "nasdaq"
    filtered = filtered[["symbol", "date", "session", "source"]].sort_values(
        ["symbol", "date"]
    ).reset_index(drop=True)

    cal_out = OUT_DIR / "earnings_calendar.parquet"
    filtered.to_parquet(cal_out, index=False)

    # anomaly diagnostic: raw symbols with '.' or '-' not in the archive, whose
    # normalized form (dots/dashes stripped) *does* match an archive symbol
    normalized_archive = {s.replace(".", "").replace("-", ""): s for s in archive}
    raw_symbols = set(raw_df["symbol"].unique())
    unmatched_punct = sorted(
        s for s in raw_symbols
        if s not in archive and ("." in s or "-" in s)
        and s.replace(".", "").replace("-", "") in normalized_archive
    )

    # cross-check
    cc = crosscheck(filtered)
    cc_out = OUT_DIR / "earnings_crosscheck.csv"
    cc.to_csv(cc_out, index=False)

    total_nasdaq = cc["nasdaq_date"].notna().sum()
    matched_nasdaq = (cc["nasdaq_date"].notna() & cc["yf_date"].notna()).sum()
    total_yf = cc["yf_date"].notna().sum()
    matched_yf = matched_nasdaq  # a matched pair counts once on each side
    session_eligible = cc["session_match"].notna().sum()
    session_agree = (cc["session_match"] == True).sum()  # noqa: E712

    # ---- stdout summary ----
    print(f"trading days in window: {len(days)}")
    print(f"days fetched: {stats['fetched']}, cached: {stats['cached']}, "
          f"warned/empty: {stats['warned_days']}/{stats['empty_days']}")
    print(f"total earnings rows (raw, all symbols): {len(raw_df)}")
    print(f"rows after archive filter: {len(filtered)}")
    print(f"distinct symbols covered: {filtered['symbol'].nunique()}")

    session_counts = filtered["session"].value_counts()
    print("session distribution:", {
        k: int(session_counts.get(k, 0)) for k in ["bmo", "amc", "unknown"]
    })

    covered = set(filtered["symbol"].unique())
    zero_cov = sorted(archive - covered)
    print(f"archive symbols with zero earnings rows: {len(zero_cov)}")
    print(f"  examples: {zero_cov[:10]}")

    if unmatched_punct:
        print(f"ANOMALY: {len(unmatched_punct)} raw Nasdaq symbols with '.'/'-' "
              f"not in archive but normalize to an archive symbol (not auto-fixed): "
              f"{unmatched_punct[:10]}")

    print("--- yfinance cross-check ---")
    print(f"sampled symbols: {cc['symbol'].nunique()} (seed={CROSSCHECK_SEED}, n={CROSSCHECK_N})")
    print(f"nasdaq rows in sample: {total_nasdaq}, matched (within +/-1d of a yf date): "
          f"{matched_nasdaq} ({matched_nasdaq / total_nasdaq * 100:.1f}%)"
          if total_nasdaq else "nasdaq rows in sample: 0")
    print(f"yfinance rows in sample: {total_yf}, matched: {matched_yf} "
          f"({matched_yf / total_yf * 100:.1f}%)" if total_yf else "yfinance rows in sample: 0")
    print(f"session-eligible matched pairs (yf has usable timestamp): {session_eligible}, "
          f"agree: {session_agree} "
          f"({session_agree / session_eligible * 100:.1f}%)"
          if session_eligible else "session-eligible matched pairs: 0")

    print(f"wrote {cal_out}: {len(filtered)} rows")
    print(f"wrote {cc_out}: {len(cc)} rows")


if __name__ == "__main__":
    main()
