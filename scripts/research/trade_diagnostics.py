"""Round-trip diagnostic pipeline for regenerated fulltest fills.

Usage: .venv/bin/python data/diagnostics/trade_diagnostics.py <name> <leg>
Reads  data/diagnostics/<name>_<leg>_fills.csv, pairs fills FIFO via
axtrade.analytics.pair_fills_fifo (the certified pairing path), enriches each
round trip with timing/regime/excursion features, writes
<name>_<leg>_trades.csv and prints an aggregate summary block (markdown-ish)
for the diagnostic report.
"""
import glob
import sys
from datetime import timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, "/home/mihai/workspace/meridian/src")
from axtrade.analytics import pair_fills_fifo  # noqa: E402

DIAG = "/home/mihai/workspace/meridian/data/diagnostics"
DATA = "/home/mihai/workspace/meridian/data/historical"
ET = ZoneInfo("America/New_York")

_bars_cache: dict[str, pd.DataFrame] = {}


def bars_for(symbol: str) -> pd.DataFrame:
    if symbol not in _bars_cache:
        f = glob.glob(f"{DATA}/{symbol}_1m_*.parquet")[0]
        df = pd.read_parquet(f)
        if "timestamp" not in df.columns:
            df = df.reset_index()
        _bars_cache[symbol] = df.sort_values("timestamp").reset_index(drop=True)
    return _bars_cache[symbol]


def daily_features(symbol: str) -> pd.DataFrame:
    df = bars_for(symbol)
    d = df.set_index("timestamp")["close"].resample("1D").last().dropna()
    feat = pd.DataFrame({"close": d})
    feat["sma20d"] = d.rolling(20).mean()
    feat["sma50d"] = d.rolling(50).mean()
    up = (feat["close"] > feat["sma20d"]) & (feat["sma20d"] > feat["sma50d"])
    down = (feat["close"] < feat["sma20d"]) & (feat["sma20d"] < feat["sma50d"])
    feat["trend"] = np.where(up, "up", np.where(down, "down", "mixed"))
    feat.loc[feat["sma50d"].isna(), "trend"] = "na"
    vol20 = d.pct_change().rolling(20).std()
    feat["vol_tercile"] = pd.qcut(vol20.rank(method="first"), 3, labels=["low", "mid", "high"])
    feat["date"] = feat.index.date
    return feat.set_index("date")


def mae_mfe(symbol: str, entry_time, exit_time, entry_price: float):
    df = bars_for(symbol)
    ts = df["timestamp"].values
    lo = np.searchsorted(ts, np.datetime64(entry_time))
    hi = np.searchsorted(ts, np.datetime64(exit_time), side="right")
    if hi <= lo:
        return np.nan, np.nan
    w = df.iloc[lo:hi]
    mae = (w["low"].min() - entry_price) / entry_price * 100
    mfe = (w["high"].max() - entry_price) / entry_price * 100
    return mae, mfe


def load_trades(name: str, leg: str) -> pd.DataFrame:
    fills = pd.read_csv(f"{DIAG}/{name}_{leg}_fills.csv", parse_dates=["filled_at"])
    fill_objs = [
        SimpleNamespace(id=i, **row)
        for i, row in enumerate(fills.to_dict("records"))
    ]
    records = pair_fills_fifo(fill_objs)
    rows = []
    for t in records:
        rows.append(
            {
                "symbol": t.symbol,
                "entry_time": pd.Timestamp(t.entry_time),
                "exit_time": pd.Timestamp(t.exit_time),
                "entry_price": float(t.entry_price),
                "exit_price": float(t.exit_price),
                "qty": float(t.quantity),
                "net_pnl": float(t.pnl),
                "commission": float(t.commission),
            }
        )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["gross_pnl"] = df["net_pnl"] + df["commission"]
    df["hold_min"] = (df["exit_time"] - df["entry_time"]).dt.total_seconds() / 60
    ent = df["entry_time"].dt.tz_localize("UTC") if df["entry_time"].dt.tz is None else df["entry_time"]
    df["entry_hour_et"] = ent.dt.tz_convert(ET).dt.hour
    df["entry_dow"] = ent.dt.tz_convert(ET).dt.day_name().str[:3]
    df["ret_pct"] = df["gross_pnl"] / (df["entry_price"] * df["qty"]) * 100

    # daily regime join
    feats = {s: daily_features(s) for s in df["symbol"].unique()}
    def jf(row, col):
        f = feats[row["symbol"]]
        d = pd.Timestamp(row["entry_time"]).date()
        return f[col].get(d, "na")
    df["day_trend"] = df.apply(lambda r: jf(r, "trend"), axis=1)
    df["day_vol"] = df.apply(lambda r: str(jf(r, "vol_tercile")), axis=1)

    # excursions (naive-UTC bar timestamps)
    maes, mfes = [], []
    for _, r in df.iterrows():
        et_ = pd.Timestamp(r["entry_time"]).tz_localize(None) if pd.Timestamp(r["entry_time"]).tz else r["entry_time"]
        xt_ = pd.Timestamp(r["exit_time"]).tz_localize(None) if pd.Timestamp(r["exit_time"]).tz else r["exit_time"]
        a, b = mae_mfe(r["symbol"], et_, xt_, r["entry_price"])
        maes.append(a)
        mfes.append(b)
    df["mae_pct"] = maes
    df["mfe_pct"] = mfes
    return df


def bucket_hold(m):
    if m < 5: return "<5m"
    if m < 30: return "5-30m"
    if m < 120: return "30m-2h"
    if m < 1440: return "2h-1d"
    return ">1d"


def agg_table(df, by):
    g = df.groupby(by, observed=True).agg(
        n=("net_pnl", "size"),
        net=("net_pnl", "sum"),
        wr=("net_pnl", lambda s: (s > 0).mean() * 100),
        avg=("net_pnl", "mean"),
    )
    return g.round(2)


def summarize(name: str, leg: str) -> None:
    df = load_trades(name, leg)
    print(f"\n## {name} {leg}: {len(df)} round trips")
    if df.empty:
        return
    df.to_csv(f"{DIAG}/{name}_{leg}_trades.csv", index=False)
    gross = df["gross_pnl"].sum()
    comm = df["commission"].sum()
    net = df["net_pnl"].sum()
    winners = df[df["net_pnl"] > 0]
    losers = df[df["net_pnl"] <= 0]
    pf = winners["net_pnl"].sum() / abs(losers["net_pnl"].sum()) if len(losers) else float("inf")
    print(f"net {net:,.0f} | gross {gross:,.0f} | commission {comm:,.0f} "
          f"({comm / abs(net) * 100 if net else 0:.1f}% of |net|) | WR {len(winners)/len(df)*100:.1f}% | PF {pf:.2f}")
    print(f"avg winner {winners['net_pnl'].mean():.2f} | avg loser {losers['net_pnl'].mean():.2f} "
          f"| median hold {df['hold_min'].median():.0f}m")
    top10_loss = losers.nsmallest(10, "net_pnl")["net_pnl"].sum()
    print(f"top-10 worst trades: {top10_loss:,.0f} ({top10_loss / losers['net_pnl'].sum() * 100 if len(losers) else 0:.1f}% of gross losses)")
    print(f"median MAE {df['mae_pct'].median():.3f}% | median MFE {df['mfe_pct'].median():.3f}% "
          f"| losers' median MFE {losers['mfe_pct'].median():.3f}%")
    df["hold_bucket"] = df["hold_min"].map(bucket_hold)
    for by in ["hold_bucket", "entry_hour_et", "day_trend", "day_vol", "symbol"]:
        print(f"\nby {by}:")
        print(agg_table(df, by).to_string())


if __name__ == "__main__":
    summarize(sys.argv[1], sys.argv[2])
