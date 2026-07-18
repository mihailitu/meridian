"""momentum rescale research (IN-SAMPLE ONLY: 2024-08-01 -> 2025-08-01).

The recorded momentum strategy never traded (trend_strength>30 is daily-scale math on 1m
bars — see momentum_gates.json). This gives the idea its first actual test by rescaling
the strength threshold to the 1m distribution, all other gates and exits unchanged.

Gates (long entry, replicating MomentumBreakout):
  regime TRENDING_UP (bullish 1m: sma10>sma20 & close>sma10; vol degenerate-low)
  trend_strength > S            <- S in {2, 3, 4} (p85-p97 of bullish bars) vs broken 30
  close > sma20_1m
  RSI14 crossing up through 50
Exit: RSI>70, or 1m regime flips TRENDING_DOWN (bearish), or -3% stop. Fill at bar close.

Pre-registered (2026-07-18, before running): variants = S in {2,3,4}; selection = highest
IS PF with >=300 trades and positive net at 10bps AND 2bps slippage/side (+commission).
"""
import glob
import json

import numpy as np
import pandas as pd

SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]
START, END = "2024-08-01", "2025-08-01"  # IS ONLY
DATA = "/home/mihai/workspace/meridian/data/historical"
QTY = 100
SL = -0.03


def wilder_rsi(close, period=14):
    delta = close.diff()
    up = delta.clip(lower=0.0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    dn = (-delta).clip(lower=0.0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rsi = 100 - 100 / (1 + up / dn)
    return rsi.where(dn > 0, 100.0)


def prep(symbol):
    f = glob.glob(f"{DATA}/{symbol}_1m_*.parquet")[0]
    df = pd.read_parquet(f)
    if "timestamp" not in df.columns:
        df = df.reset_index()
    df = df[(df["timestamp"] >= START) & (df["timestamp"] < END)].reset_index(drop=True)
    c = df["close"]
    sma10, sma20 = c.rolling(10).mean(), c.rolling(20).mean()
    df["bullish"] = (sma10 > sma20) & (c > sma10)
    df["bearish"] = (sma10 < sma20) & (c < sma10)
    sma_diff = (sma10 - sma20) / sma20 * 100
    pvs = (c - sma10) / sma10 * 100
    pvl = (c - sma20) / sma20 * 100
    raw = (sma_diff.abs() * 10 + pvs.abs() * 2 + pvl.abs() * 3).clip(upper=100.0)
    neutral = ~df["bullish"] & ~df["bearish"]
    df["strength"] = raw.where(~neutral, raw * 0.5)
    df["sma20"] = sma20
    df["rsi"] = wilder_rsi(c)
    df["rsi_cross"] = (df["rsi"].shift(1) <= 50) & (df["rsi"] > 50)
    return df


def simulate(df, s_thresh):
    c = df["close"].values
    entry_ok = (df["bullish"] & (df["strength"] > s_thresh) & (c > df["sma20"])
                & df["rsi_cross"] & df["sma20"].notna() & df["rsi"].notna()).values
    rsi = df["rsi"].values
    bearish = df["bearish"].values
    ts = df["timestamp"].values
    trades, in_pos, entry_px, entry_i = [], False, 0.0, 0
    for i in range(len(df)):
        if in_pos:
            pnl = (c[i] - entry_px) / entry_px
            if rsi[i] > 70 or bearish[i] or pnl < SL:
                trades.append({"entry_ts": ts[entry_i], "exit_ts": ts[i],
                               "entry": entry_px, "exit": c[i],
                               "hold_min": (ts[i] - ts[entry_i]) / np.timedelta64(1, "m")})
                in_pos = False
        elif entry_ok[i]:
            in_pos, entry_px, entry_i = True, c[i], i
    return trades


def evaluate(all_trades, slip_bps):
    if not all_trades:
        return {"trades": 0}
    net = np.array([(t["exit"] * (1 - slip_bps / 1e4) - t["entry"] * (1 + slip_bps / 1e4)) * QTY
                    - 2 * max(1.0, 0.005 * QTY) for t in all_trades])
    win, loss = net[net > 0], net[net <= 0]
    return {"trades": len(net), "net": round(float(net.sum())),
            "pf": round(float(win.sum() / abs(loss.sum())), 2) if len(loss) and loss.sum() else float("inf"),
            "wr": round(float((net > 0).mean() * 100), 1),
            "avg": round(float(net.mean()), 2),
            "med_hold": round(float(np.median([t["hold_min"] for t in all_trades])))}


if __name__ == "__main__":
    dfs = {s: prep(s) for s in SYMBOLS}
    results = {}
    for s_thresh in (2.0, 3.0, 4.0):
        allt = []
        for df in dfs.values():
            allt += simulate(df, s_thresh)
        results[f"S{s_thresh}"] = {f"slip{int(b)}": evaluate(allt, b) for b in (10.0, 2.0, 0.0)}
        r10, r2, r0 = (results[f"S{s_thresh}"][k] for k in ("slip10", "slip2", "slip0"))
        print(f"S>{s_thresh}: n {r0.get('trades',0):5d} hold {r0.get('med_hold',0):4d}m "
              f"| 10bps net {r10.get('net',0):8d} PF {r10.get('pf',0):5.2f} "
              f"| 2bps net {r2.get('net',0):8d} PF {r2.get('pf',0):5.2f} WR {r2.get('wr',0):4.1f}% "
              f"| 0bps net {r0.get('net',0):8d} PF {r0.get('pf',0):5.2f}")
    with open("/home/mihai/workspace/meridian/data/diagnostics/momentum_research_results.json", "w") as f:
        json.dump(results, f, indent=1)
