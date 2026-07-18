"""multi_timeframe exit-redesign research (IN-SAMPLE ONLY: 2024-08-01 -> 2025-08-01).

Vectorized-state replication of MultiTimeframe (src/axtrade/strategies/multi_timeframe.py)
on 1m parquet, then pre-registered exit/entry variants. OOS is deliberately never loaded;
the chosen variant graduates to a fulltest IS pass + single OOS shot.

Baseline mechanics replicated:
  trend: current 1m close vs mean(final closes of prev 19 5m-buckets + current close)
         ("up" if strictly greater, else "down")
  entry: no position & trend up & not bearish_1m & RSI14 in [40,60]
         & |close-sma20_1m|/sma20_1m <= 0.003            (fill at bar close, 100 sh)
  exit:  trend down -> close; else TP +3% / SL -2%        (fill at bar close)
  bearish_1m (TRENDING_DOWN proxy, vol degenerate-low): sma10<sma20 & close<sma10

Variants (pre-registered):
  V1(b): flip-exit only when close < trend_sma*(1-b), b in {0.001, 0.002, 0.003}
  V2:    flip-exit only when position is in profit (SL/TP unchanged)
  V3(d): entry additionally requires close >= trend_sma*(1+d), d in {0.001, 0.002}
  V4:    best V1 or V2 combined with best V3
Selection rule (pre-registered): highest IS PF among variants with >=300 trades/year
across the 5 symbols AND positive net after 1c/share/side extra cost; ties -> simpler.
"""
import glob
import json

import numpy as np
import pandas as pd

SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]
START, END = "2024-08-01", "2025-08-01"  # IS ONLY
DATA = "/home/mihai/workspace/meridian/data/historical"
QTY = 100
COMMISSION = 1.0  # per fill
TP, SL = 0.03, -0.02


def wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0.0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    dn = (-delta).clip(lower=0.0).ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rsi = 100 - 100 / (1 + up / dn)
    return rsi.where(dn > 0, 100.0)


def prep(symbol: str) -> pd.DataFrame:
    f = glob.glob(f"{DATA}/{symbol}_1m_*.parquet")[0]
    df = pd.read_parquet(f)
    if "timestamp" not in df.columns:
        df = df.reset_index()
    df = df[(df["timestamp"] >= START) & (df["timestamp"] < END)].reset_index(drop=True)
    c = df["close"]
    df["rsi"] = wilder_rsi(c)
    df["sma20_1m"] = c.rolling(20).mean()
    sma10 = c.rolling(10).mean()
    df["bearish"] = (sma10 < df["sma20_1m"]) & (c < sma10)

    # trend uses COMPLETED 5m buckets only (the forming candle lives outside
    # _trend_closes): "current" = last completed bucket close, SMA20 over the
    # last 20 completed closes (including that one). Both stale within a bucket.
    bucket = df["timestamp"].dt.floor("5min")
    bucket_final = c.groupby(bucket).last()
    t_close = bucket_final.shift(1)                       # last completed close
    t_sma = bucket_final.rolling(20).mean().shift(1)      # SMA20 of completed
    df["trend_close"] = bucket.map(t_close)
    df["trend_sma"] = bucket.map(t_sma)
    df["trend_up"] = df["trend_close"] > df["trend_sma"]
    df["entry_ok"] = (
        df["trend_up"]
        & ~df["bearish"]
        & df["rsi"].between(40, 60)
        & ((c - df["sma20_1m"]).abs() / df["sma20_1m"] <= 0.003)
        & df["trend_sma"].notna()
        & df["sma20_1m"].notna()
    )
    return df


def simulate(df: pd.DataFrame, hyst: float = 0.0, profit_gated: bool = False,
             entry_dist: float = 0.0) -> list[dict]:
    close = df["close"].values
    trend_sma = df["trend_sma"].values
    trend_close = df["trend_close"].values
    entry_ok = df["entry_ok"].values
    ts = df["timestamp"].values
    trades = []
    in_pos = False
    entry_px = 0.0
    entry_i = 0
    for i in range(len(df)):
        if np.isnan(trend_sma[i]):
            continue
        if in_pos:
            pnl_pct = (close[i] - entry_px) / entry_px
            flip = trend_close[i] <= trend_sma[i] * (1 - hyst)
            if profit_gated and flip and pnl_pct <= 0:
                flip = False
            if flip or pnl_pct >= TP or pnl_pct <= SL:
                trades.append(
                    {"entry_time": ts[entry_i], "exit_time": ts[i],
                     "entry": entry_px, "exit": close[i],
                     "gross": (close[i] - entry_px) * QTY,
                     "hold_min": (ts[i] - ts[entry_i]) / np.timedelta64(1, "m")}
                )
                in_pos = False
        else:
            if entry_ok[i] and (entry_dist == 0.0 or trend_close[i] >= trend_sma[i] * (1 + entry_dist)):
                in_pos = True
                entry_px = close[i]
                entry_i = i
    return trades


def evaluate(all_trades: list[dict], extra_cost_per_share: float = 0.0) -> dict:
    if not all_trades:
        return {"trades": 0}
    g = np.array([t["gross"] for t in all_trades])
    costs = 2 * COMMISSION + 2 * extra_cost_per_share * QTY
    net = g - costs
    win = net[net > 0]
    loss = net[net <= 0]
    return {
        "trades": len(net),
        "net": round(float(net.sum())),
        "pf": round(float(win.sum() / abs(loss.sum())), 2) if len(loss) and loss.sum() != 0 else float("inf"),
        "wr": round(float((net > 0).mean() * 100), 1),
        "avg": round(float(net.mean()), 2),
        "med_hold_m": round(float(np.median([t["hold_min"] for t in all_trades]))),
    }


def run_variant(dfs, **kw):
    allt = []
    for df in dfs.values():
        allt += simulate(df, **kw)
    return {"base_cost": evaluate(allt), "plus_1c": evaluate(allt, 0.01)}


if __name__ == "__main__":
    dfs = {s: prep(s) for s in SYMBOLS}
    results = {}
    results["V0_baseline"] = run_variant(dfs)
    for b in (0.001, 0.002, 0.003):
        results[f"V1_hyst_{b}"] = run_variant(dfs, hyst=b)
    results["V2_profit_gated"] = run_variant(dfs, profit_gated=True)
    for d in (0.001, 0.002):
        results[f"V3_dist_{d}"] = run_variant(dfs, entry_dist=d)
    print(json.dumps(results, indent=1))
    with open("/home/mihai/workspace/meridian/data/diagnostics/mtf_research_results.json", "w") as f:
        json.dump(results, f, indent=1)
