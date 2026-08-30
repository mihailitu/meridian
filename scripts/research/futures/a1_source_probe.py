"""T1 Phase A1: source probe — is a continuous CL series back-adjusted?

Tier-2 scratch script (docs/t1-futures-plan.md §A1). Diagnostic logic:

An UNADJUSTED front-month splice always trades at (near) the front contract
price, so its level tracks spot WTI through time and its long-run cumulative
return ~= the spot price change. A BACK-ADJUSTED series preserves the
investor's roll-inclusive return, so through the 2006-2010 super-contango its
level diverges massively below spot (the true long-futures investor lost far
more than the spot change).

Inputs (data/futures/probe/): yahoo_clf.csv (yfinance CL=F, period=max),
fred_wti_spot.csv (FRED DCOILWTICO), optionally stooq_clf.csv (manual
browser download — stooq.com blocks non-browser clients).

For each candidate series prints: level-vs-spot tracking (median |basis|,
p95), cumulative return vs spot change over 2006-2016 (the contango decade),
and a roll-artifact scan (daily-return spikes with no matching spot move).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

PROBE = Path("data/futures/probe")


def load_spot() -> pd.Series:
    s = pd.read_csv(PROBE / "fred_wti_spot.csv", parse_dates=["observation_date"])
    s = s.set_index("observation_date")["DCOILWTICO"].dropna()
    return s


def load_yahoo() -> pd.Series:
    df = pd.read_csv(PROBE / "yahoo_clf.csv", parse_dates=["Date"])
    df["Date"] = pd.to_datetime(df["Date"], utc=True).dt.tz_localize(None).dt.normalize()
    return df.set_index("Date")["Close"].dropna()


def load_stooq() -> pd.Series | None:
    p = PROBE / "stooq_clf.csv"
    if not p.exists() or not p.read_text().startswith("Date,"):
        return None
    df = pd.read_csv(p, parse_dates=["Date"])
    return df.set_index("Date")["Close"].dropna()


def diagnose(name: str, series: pd.Series, spot: pd.Series) -> None:
    joint = pd.concat({"f": series, "s": spot}, axis=1).dropna()
    basis = (joint["f"] - joint["s"]) / joint["s"]
    print(f"\n=== {name} ===  {len(joint)} overlapping days "
          f"({joint.index.min().date()} → {joint.index.max().date()})")
    print(f"level vs spot: median |basis| {basis.abs().median():.2%}, "
          f"p95 |basis| {basis.abs().quantile(0.95):.2%}")

    win = joint.loc["2006":"2016"]
    if len(win) > 500:
        f_ret = win["f"].iloc[-1] / win["f"].iloc[0] - 1
        s_ret = win["s"].iloc[-1] / win["s"].iloc[0] - 1
        print(f"2006-2016 cumret: series {f_ret:+.1%} vs spot {s_ret:+.1%} "
              f"(unadjusted splice ~= spot; true futures return far below)")

    # roll-artifact scan: series daily moves >3% with |spot move| <1% same day
    r_f = joint["f"].pct_change()
    r_s = joint["s"].pct_change()
    artifact = (r_f.abs() > 0.03) & (r_s.abs() < 0.01)
    per_yr = artifact.sum() / (len(joint) / 252)
    print(f"roll-artifact candidates (|series ret|>3%, |spot ret|<1%): "
          f"{artifact.sum()} days ({per_yr:.1f}/yr)")
    if artifact.sum():
        days = r_f[artifact]
        print(f"  mean {days.mean():+.2%}, sum {days.sum():+.1%} over sample; "
              f"day-of-month histogram: "
              f"{np.bincount(days.index.day, minlength=32)[1:].tolist()}")


def main() -> None:
    spot = load_spot()
    diagnose("Yahoo CL=F", load_yahoo(), spot)
    stooq = load_stooq()
    if stooq is not None:
        diagnose("Stooq CL.F", stooq, spot)
    else:
        print("\n(stooq_clf.csv not present — download manually from "
              "https://stooq.com/q/d/l/?s=cl.f&i=d)")


if __name__ == "__main__":
    main()
