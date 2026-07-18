"""overnight_reversal redesign research (IN-SAMPLE ONLY: 2024-08-01 -> 2025-08-01).

Replicates OvernightReversalStrategy on 1m parquet, then pre-registered variants.
OOS never loaded; any surviving candidate goes to the fulltest gate.

Baseline: session open = OPEN of first bar >=09:30 ET; entry in [15:50,16:00) ET at the
first bar with close/session_open-1 <= -1%; fill at bar close; one entry/symbol/day.
Exit at the close of the first bar >=09:30 ET on a later day.

Variants (pre-registered 2026-07-18, before any variant was run):
  V1(X): tail filter - enter only when intraday return in [-X%, -1%], X in {3, 4, 5}
  V2(tp): overnight take-profit - from 04:00 ET next day, exit at first bar whose close
          >= entry*(1+tp), tp in {0.005, 0.010}; otherwise baseline exit
  V3: best V1 x best V2
Selection rule: highest IS PF among variants with >=100 trades AND positive net under
the platform cost model (10bps slippage/side + commission max($1, 0.5c/sh)) AND still
positive at 2bps/side. Ties -> simpler variant.
"""
import glob
import json

import numpy as np
import pandas as pd

SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]
START, END = "2024-08-01", "2025-08-01"  # IS ONLY
DATA = "/home/mihai/workspace/meridian/data/historical"
QTY = 100
THRESH = 0.01


def load(symbol: str) -> pd.DataFrame:
    f = glob.glob(f"{DATA}/{symbol}_1m_*.parquet")[0]
    df = pd.read_parquet(f)
    if "timestamp" not in df.columns:
        df = df.reset_index()
    df = df[(df["timestamp"] >= START) & (df["timestamp"] < END)].reset_index(drop=True)
    et = df["timestamp"].dt.tz_localize("UTC").dt.tz_convert("America/New_York")
    df["et_date"] = et.dt.date
    df["et_time"] = et.dt.time
    return df


def simulate(df: pd.DataFrame, tail_max: float | None = None, tp: float | None = None) -> list[dict]:
    from datetime import time as T
    t0930, t1550, t1600, t0400 = T(9, 30), T(15, 50), T(16, 0), T(4, 0)
    trades = []
    days = sorted(df["et_date"].unique())
    day_groups = {d: g for d, g in df.groupby("et_date")}
    for di, day in enumerate(days):
        g = day_groups[day]
        rth = g[g["et_time"] >= t0930]
        if rth.empty:
            continue
        session_open = rth.iloc[0]["open"]
        if session_open <= 0:
            continue
        win = g[(g["et_time"] >= t1550) & (g["et_time"] < t1600)]
        if win.empty:
            continue
        ret = win["close"] / session_open - 1.0
        qual = win[ret <= -THRESH]
        if tail_max is not None:
            qual = qual[(qual["close"] / session_open - 1.0) >= -tail_max]
        if qual.empty:
            continue
        entry_row = qual.iloc[0]
        entry_px = entry_row["close"]
        entry_ts = entry_row["timestamp"]

        # exit: scan later days
        exit_px, exit_ts = None, None
        for dj in range(di + 1, min(di + 6, len(days))):
            g2 = day_groups[days[dj]]
            if tp is not None:
                pre = g2[(g2["et_time"] >= t0400) & (g2["et_time"] < t0930)]
                hit = pre[pre["close"] >= entry_px * (1 + tp)]
                if not hit.empty:
                    exit_px = hit.iloc[0]["close"]
                    exit_ts = hit.iloc[0]["timestamp"]
                    break
            rth2 = g2[g2["et_time"] >= t0930]
            if not rth2.empty:
                exit_px = rth2.iloc[0]["close"]
                exit_ts = rth2.iloc[0]["timestamp"]
                break
        if exit_px is None:
            continue
        trades.append({"entry_ts": entry_ts, "exit_ts": exit_ts,
                       "entry": entry_px, "exit": exit_px,
                       "intraday_ret": float(entry_px / session_open - 1.0)})
    return trades


def evaluate(all_trades: list[dict], slip_bps: float) -> dict:
    if not all_trades:
        return {"trades": 0}
    net = []
    for t in all_trades:
        e = t["entry"] * (1 + slip_bps / 1e4)
        x = t["exit"] * (1 - slip_bps / 1e4)
        net.append((x - e) * QTY - 2 * max(1.0, 0.005 * QTY))
    net = np.array(net)
    win, loss = net[net > 0], net[net <= 0]
    return {"trades": len(net), "net": round(float(net.sum())),
            "pf": round(float(win.sum() / abs(loss.sum())), 2) if len(loss) and loss.sum() else float("inf"),
            "wr": round(float((net > 0).mean() * 100), 1),
            "avg": round(float(net.mean()), 2)}


if __name__ == "__main__":
    dfs = {s: load(s) for s in SYMBOLS}
    variants = {"V0_baseline": {}}
    for x in (0.03, 0.04, 0.05):
        variants[f"V1_tail_{int(x*100)}pct"] = {"tail_max": x}
    for tp in (0.005, 0.010):
        variants[f"V2_tp_{tp}"] = {"tp": tp}
    results = {}
    for name, kw in variants.items():
        allt = []
        for df in dfs.values():
            allt += simulate(df, **kw)
        results[name] = {f"slip{int(s)}": evaluate(allt, s) for s in (10.0, 2.0, 0.0)}
        r10, r2, r0 = results[name]["slip10"], results[name]["slip2"], results[name]["slip0"]
        print(f"{name:16s} n {r10.get('trades',0):4d} | 10bps net {r10.get('net',0):7d} PF {r10.get('pf',0):5.2f} "
              f"| 2bps net {r2.get('net',0):7d} PF {r2.get('pf',0):5.2f} WR {r2.get('wr',0):4.1f}% "
              f"| 0bps net {r0.get('net',0):7d} PF {r0.get('pf',0):5.2f}")
    with open("/home/mihai/workspace/meridian/data/diagnostics/onr_research_results.json", "w") as f:
        json.dump(results, f, indent=1)
