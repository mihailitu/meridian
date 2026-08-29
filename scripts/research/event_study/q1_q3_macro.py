"""E4 Phase 1 analysis: Q1 (large-move attribution) + Q3 (event-conditional drift).

Tier-2 scratch script. Definitions are FROZEN in docs/event-study-plan.md §4:
  - large move: |daily log return| > 2 x trailing 63-day sigma (shifted; the
    day being classified is excluded from its own sigma)
  - Q3 windows: FOMC {t-1c->tc, tc->t+1c, t+1c->t+3c};
                CPI/NFP {t-1c->to, to->tc}   (08:30 ET releases are pre-open)
  - notable: |t| >= 2 (all rows reported regardless)

Index: ^GSPC daily (Yahoo), 2000-01-02 onward. Each analysis restricts itself
to the event calendar's coverage window for the event type involved (outside
it, "no event row" means "not covered"). FOMC uses scheduled meetings only in
Q3; Q1 attribution counts unscheduled FOMC actions too (they are event days).

Outputs: data/research/event_study/{q1_attribution.csv,q3_drift.csv} + stdout.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, "src")
from axtrade.research.events import coverage, event_dates, load_event_calendar  # noqa: E402

OUT_DIR = Path("data/research/event_study")
SIGMA_WINDOW = 63
LARGE_Z = 2.0


def load_index() -> pd.DataFrame:
    import yfinance as yf

    cache = OUT_DIR / "gspc_daily.parquet"
    if cache.exists():
        px = pd.read_parquet(cache)
    else:
        px = yf.Ticker("^GSPC").history(start="1999-06-01", auto_adjust=False)
        px.index = px.index.tz_localize(None)
        px = px[["Open", "Close"]]
        px.to_parquet(cache)
    px["ret"] = np.log(px["Close"] / px["Close"].shift(1))
    px["sigma"] = px["ret"].rolling(SIGMA_WINDOW).std().shift(1)
    px["z"] = px["ret"] / px["sigma"]
    return px.loc["2000-01-01":]


def welch_t(a: np.ndarray, b: np.ndarray) -> float:
    va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
    return (a.mean() - b.mean()) / np.sqrt(va + vb)


def q1(px: pd.DataFrame, cal: pd.DataFrame) -> pd.DataFrame:
    flags = pd.DataFrame(index=px.index)
    for ev in ("fomc", "cpi", "nfp"):
        dates = event_dates(cal, ev, scheduled_only=False)
        flags[ev] = px.index.isin(dates)

    # clean 3-way attribution needs all three calendars covering: intersect
    starts, ends = zip(*(coverage(cal, ev) for ev in ("fomc", "cpi", "nfp")))
    lo, hi = max(starts), min(ends)
    sub = px.loc[lo:hi].dropna(subset=["z"])
    f = flags.loc[sub.index]
    large = sub["z"].abs() > LARGE_Z

    rows = []
    for label, mask in [
        ("fomc", f["fomc"]), ("cpi", f["cpi"]), ("nfp", f["nfp"]),
        ("any_event", f.any(axis=1)), ("no_event", ~f.any(axis=1)),
    ]:
        n_days = int(mask.sum())
        n_large = int((large & mask).sum())
        base = n_days / len(sub)                    # share of days
        share = n_large / large.sum()               # share of large moves
        rows.append({
            "category": label, "days": n_days, "large_moves": n_large,
            "share_of_days": round(base, 4), "share_of_large_moves": round(share, 4),
            "lift": round(share / base, 2) if base else np.nan,
            "p_large_given_event": round(n_large / n_days, 4) if n_days else np.nan,
        })
    out = pd.DataFrame(rows)
    out.attrs["window"] = f"{lo.date()} -> {hi.date()}"
    out.attrs["n_days"] = len(sub)
    out.attrs["n_large"] = int(large.sum())
    return out


def q3(px: pd.DataFrame, cal: pd.DataFrame) -> pd.DataFrame:
    logc = np.log(px["Close"])
    logo = np.log(px["Open"])
    pos = {d: i for i, d in enumerate(px.index)}
    n = len(px)

    def series_for(dates, fn):
        vals = []
        for d in dates:
            i = pos.get(d)
            if i is None or i < 1 or i + 3 >= n:
                continue
            vals.append(fn(i))
        return np.array(vals)

    windows = {
        ("fomc", "t-1c->tc"):   lambda i: logc.iloc[i] - logc.iloc[i - 1],
        ("fomc", "tc->t+1c"):   lambda i: logc.iloc[i + 1] - logc.iloc[i],
        ("fomc", "t+1c->t+3c"): lambda i: logc.iloc[i + 3] - logc.iloc[i + 1],
        ("cpi", "t-1c->to"):    lambda i: logo.iloc[i] - logc.iloc[i - 1],
        ("cpi", "to->tc"):      lambda i: logc.iloc[i] - logo.iloc[i],
        ("nfp", "t-1c->to"):    lambda i: logo.iloc[i] - logc.iloc[i - 1],
        ("nfp", "to->tc"):      lambda i: logc.iloc[i] - logo.iloc[i],
    }

    rows = []
    for (ev, wname), fn in windows.items():
        dates = event_dates(cal, ev, scheduled_only=True)
        lo, hi = coverage(cal, ev)
        in_win = px.loc[lo:hi].index
        ev_dates = [d for d in dates if d in pos]
        ev_vals = series_for(ev_dates, fn)
        base_dates = in_win.difference(pd.DatetimeIndex(ev_dates))
        base_vals = series_for(base_dates, fn)
        rows.append({
            "event": ev, "window": wname, "n": len(ev_vals),
            "mean_bp": round(ev_vals.mean() * 1e4, 1),
            "median_bp": round(np.median(ev_vals) * 1e4, 1),
            "std_bp": round(ev_vals.std(ddof=1) * 1e4, 1),
            "base_mean_bp": round(base_vals.mean() * 1e4, 1),
            "t_vs_zero": round(ev_vals.mean() / (ev_vals.std(ddof=1) / np.sqrt(len(ev_vals))), 2),
            "t_vs_base": round(welch_t(ev_vals, base_vals), 2),
        })
    return pd.DataFrame(rows)


def main() -> None:
    cal = load_event_calendar()
    px = load_index()
    print(f"index days: {len(px)} ({px.index[0].date()} -> {px.index[-1].date()})")

    q1_df = q1(px, cal)
    print(f"\nQ1 attribution (window {q1_df.attrs['window']}, "
          f"{q1_df.attrs['n_days']} days, {q1_df.attrs['n_large']} large moves):")
    print(q1_df.to_string(index=False))
    q1_df.to_csv(OUT_DIR / "q1_attribution.csv", index=False)

    q3_df = q3(px, cal)
    print("\nQ3 event-conditional drift (scheduled events, per-event coverage):")
    print(q3_df.to_string(index=False))
    q3_df.to_csv(OUT_DIR / "q3_drift.csv", index=False)


if __name__ == "__main__":
    main()
