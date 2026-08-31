"""T1 A-lite: cross-check the IBKR-built CL continuous series + roll hygiene.

Tier-2 scratch script (docs/t1-futures-plan.md, A-lite track). Two audits:

1. **CL vs independent sources.** Compare the A3 continuous returns against
   Yahoo CL=F (an unadjusted front-month splice — should agree closely on
   non-roll days, diverge only where Yahoo splices) and the raw active close
   against FRED WTI spot (basis should be small and smooth). This is a
   machinery corroboration on the overlapping ~1y leg, not a data-quality
   certification of either source.
2. **Roll hygiene, all roots.** For every scheduled day, confirm the active
   contract ranks in the top 2 by volume among all contracts trading that
   day. Days where it doesn't are flagged — a systematic run of them would
   mean the roll rule is holding the wrong contract.

Usage:
    .venv/bin/python scripts/research/futures/a3_crosscheck.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from axtrade.research.futures import (  # noqa: E402
    build_continuous,
    build_roll_schedule,
    coverage_start,
    load_root,
)

PROBE = Path("data/futures/probe")
ROOTS = ["CL", "ES", "GC", "ZN", "6E"]


def crosscheck_cl() -> None:
    contracts = load_root("CL")
    start = coverage_start(contracts)
    cont = build_continuous(contracts, start=start)
    print(f"CL continuous: {cont.index[0].date()} → {cont.index[-1].date()}, "
          f"{len(cont)} days, {int(cont['is_roll'].sum())} rolls")

    # --- vs Yahoo CL=F (front-month splice) ---
    y = pd.read_csv(PROBE / "yahoo_clf.csv")
    y["date"] = pd.to_datetime(y["Date"].str[:10])
    y = y.set_index("date")["Close"].astype(float)
    y_ret = y.pct_change()

    common = cont.index.intersection(y_ret.index)
    ours = cont.loc[common, "ret"]
    theirs = y_ret.loc[common]
    mask = ours.notna() & theirs.notna()
    diff = (ours - theirs)[mask]
    nonroll = mask & ~cont.loc[common, "is_roll"]

    print("\n[CL vs Yahoo CL=F returns]")
    print(f"  common days: {int(mask.sum())}  "
          f"corr: {ours[mask].corr(theirs[mask]):.4f}")
    print(f"  non-roll days: mean|diff| {diff[nonroll[mask.index[mask]]].abs().mean()*1e4:.1f} bp, "
          f"max|diff| {diff[nonroll[mask.index[mask]]].abs().max()*1e4:.1f} bp")
    big = diff[diff.abs() > 0.005]
    print(f"  days with |diff| > 50 bp: {len(big)}")
    for day, d in big.items():
        flag = "ROLL" if cont.loc[day, "is_roll"] else "    "
        y_prev = y_ret.index[y_ret.index.get_loc(day) - 1]
        print(f"    {day.date()} {flag} ours {ours[day]*100:+.2f}%  "
              f"yahoo {theirs[day]*100:+.2f}%  (yahoo close {y[y_prev]:.2f}→{y[day]:.2f}, "
              f"contract {cont.loc[day, 'contract']})")

    # --- raw active close vs FRED spot ---
    f = pd.read_csv(PROBE / "fred_wti_spot.csv")
    f["date"] = pd.to_datetime(f["observation_date"])
    f = f.set_index("date")["DCOILWTICO"].astype(float).dropna()
    common_f = cont.index.intersection(f.index)
    basis = cont.loc[common_f, "close_raw"] / f.loc[common_f] - 1.0
    print("\n[CL raw front close vs FRED WTI spot]")
    print(f"  common days: {len(basis)}  median|basis| {basis.abs().median()*100:.2f}%  "
          f"p95|basis| {basis.abs().quantile(0.95)*100:.2f}%  "
          f"max|basis| {basis.abs().max()*100:.2f}%")


def roll_hygiene(root: str) -> None:
    contracts = load_root(root)
    start = coverage_start(contracts)
    sched = build_roll_schedule(contracts, start=start)
    by_symbol = {c.symbol: c for c in contracts}

    flagged = []
    for day, sym in sched.items():
        vols = {
            c.symbol: float(c.bars.loc[day, "volume"])
            for c in contracts if day in c.bars.index
        }
        if sym not in vols:
            continue  # active contract holiday gap; builder skips these days
        rank = sorted(vols.values(), reverse=True).index(vols[sym]) + 1
        if rank > 2:
            flagged.append((day, sym, rank, vols[sym], max(vols.values())))

    n = len(sched)
    print(f"{root}: {n} days, {len(flagged)} days active contract below "
          f"volume rank 2 ({len(flagged)/n*100:.1f}%)")
    for day, sym, rank, v, vmax in flagged[:8]:
        print(f"    {day.date()} {sym} rank {rank} (vol {v:.0f} vs max {vmax:.0f})")
    if len(flagged) > 8:
        print(f"    ... {len(flagged) - 8} more")


def main() -> None:
    crosscheck_cl()
    print("\n[roll hygiene: active contract volume rank]")
    for root in ROOTS:
        roll_hygiene(root)


if __name__ == "__main__":
    main()
