"""Momentum entry-gate co-fire analysis (diagnostic, vectorized from parquet).

Replicates MomentumBreakout's four entry gates offline on 1m bars for the
narrowed universe, per IS/OOS leg, and reports individual/joint pass rates.
Faithful to src/axtrade/{strategies/momentum.py,indicators/regime.py,indicators/rsi.py}:
  g_regime:   regime in (TRENDING_UP, BREAKOUT). On 1m data volatility percentile
              is structurally <25 (audit P2-11), so this reduces to trend==BULLISH:
              sma10 > sma20 and close > sma10.  (vol computed anyway to confirm)
  g_strength: trend_strength > 30, strength = min(100, |sma_diff_pct|*10
              + |price_vs_short|*2 + |price_vs_long|*3)
  g_sma:      close > sma20
  g_rsi:      prev_rsi <= 50 < rsi (Wilder RSI-14, ewm approximation)
"""
import glob
import json

import numpy as np
import pandas as pd

SYMBOLS = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA"]
LEGS = {"IS": ("2024-08-01", "2025-08-01"), "OOS": ("2025-08-01", "2026-02-01")}
DATA = "/home/mihai/workspace/meridian/data/historical"


def wilder_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - 100 / (1 + rs)
    return rsi.where(avg_loss > 0, 100.0)


def analyze(symbol: str, start: str, end: str) -> dict:
    f = glob.glob(f"{DATA}/{symbol}_1m_*.parquet")[0]
    df = pd.read_parquet(f)
    if "timestamp" not in df.columns:
        df = df.reset_index()
    df = df[(df["timestamp"] >= start) & (df["timestamp"] < end)].reset_index(drop=True)

    c = df["close"]
    sma10 = c.rolling(10).mean()
    sma20 = c.rolling(20).mean()

    sma_diff_pct = (sma10 - sma20) / sma20 * 100
    price_vs_short = (c - sma10) / sma10 * 100
    price_vs_long = (c - sma20) / sma20 * 100
    strength_raw = (
        sma_diff_pct.abs() * 10 + price_vs_short.abs() * 2 + price_vs_long.abs() * 3
    ).clip(upper=100.0)

    bullish = (sma10 > sma20) & (c > sma10)
    bearish = (sma10 < sma20) & (c < sma10)
    neutral = ~bullish & ~bearish
    strength = strength_raw.where(~neutral, strength_raw * 0.5)

    # volatility percentile as regime.py computes it (1m returns, sqrt(252))
    ret = c.pct_change()
    realized_vol = ret.rolling(20).std(ddof=0)
    vol_pct = (realized_vol * np.sqrt(252) * 100 / 30.0 * 50).clip(upper=100.0)

    rsi = wilder_rsi(c)
    prev_rsi = rsi.shift(1)

    g_regime = bullish & (vol_pct < 60)  # LOW/NORMAL -> TRENDING_UP
    g_breakout = bullish & (vol_pct >= 60) & (strength > 70)  # BREAKOUT
    g_regime_all = g_regime | g_breakout
    g_strength = strength > 30.0
    g_sma = c > sma20
    g_rsi = (prev_rsi <= 50) & (rsi > 50)

    cofire = g_regime_all & g_strength & g_sma & g_rsi
    n = len(df)
    return {
        "bars": n,
        "pct_bullish": float(bullish.mean() * 100),
        "pct_regime_gate": float(g_regime_all.mean() * 100),
        "pct_breakout_reachable": float(g_breakout.mean() * 100),
        "pct_strength_gt30": float(g_strength.mean() * 100),
        "pct_strength_gt30_given_bullish": float(
            (g_strength & bullish).sum() / max(bullish.sum(), 1) * 100
        ),
        "pct_sma": float(g_sma.mean() * 100),
        "pct_rsi_cross": float(g_rsi.mean() * 100),
        "strength_p50_bullish": float(strength[bullish].median()) if bullish.any() else None,
        "strength_p99_bullish": float(strength[bullish].quantile(0.99)) if bullish.any() else None,
        "strength_max": float(strength.max()),
        "vol_pct_p50": float(vol_pct.median()),
        "vol_pct_max": float(vol_pct.max()),
        "cofire_count": int(cofire.sum()),
        "cofire_wo_strength": int((g_regime_all & g_sma & g_rsi).sum()),
    }


out = {}
for leg, (start, end) in LEGS.items():
    for sym in SYMBOLS:
        out[f"{leg}:{sym}"] = analyze(sym, start, end)

print(json.dumps(out, indent=1))
with open("/home/mihai/workspace/meridian/data/diagnostics/momentum_gates.json", "w") as f:
    json.dump(out, f, indent=1)
