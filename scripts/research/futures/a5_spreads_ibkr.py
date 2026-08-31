"""T1 A5: empirical bid/ask spreads for the spec-table universe (paper TWS).

Tier-2 scratch script (docs/t1-futures-plan.md §A5). Streaming quotes are
unavailable on this account (no futures market-data subscription, even
delayed), but the historical service serves BID_ASK bars: per bar,
open = time-averaged bid, close = time-averaged ask (IBKR convention), so
close - open is the average quoted spread over the bar. Pulls hourly RTH
bars over the last few sessions for every front contract in
config/futures_specs.csv and writes the spread distribution in ticks, USD
and bp of price to config/futures_spreads.csv (merged into the cost table by
a5_cost_table.py).

formatDate=2 (epoch) is required: intraday bars carry an exchange tz name
(US/Central) that this machine's zoneinfo lacks; daily bars never hit it.

Safety: paper ports only, clientId 94, aborts unless the account looks like
paper (D*). Historical-data requests only; no orders of any kind.

Usage:
    .venv/bin/python scripts/research/futures/a5_spreads_ibkr.py [--days 5]
"""

from __future__ import annotations

import argparse
import asyncio
import time
from datetime import date
from pathlib import Path

import pandas as pd

asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB, Contract, util  # noqa: E402

SPECS = Path("config/futures_specs.csv")
OUT = Path("config/futures_spreads.csv")
PAPER_PORTS = {7497, 4002}
CLIENT_ID = 94


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7497)
    ap.add_argument("--days", type=int, default=5)
    ap.add_argument("--pace", type=float, default=10.0)
    args = ap.parse_args()
    if args.port not in PAPER_PORTS:
        raise SystemExit(f"refusing port {args.port}: paper ports only {sorted(PAPER_PORTS)}")

    specs = pd.read_csv(SPECS)
    ib = IB()
    ib.connect(args.host, args.port, clientId=CLIENT_ID, timeout=40)
    acct = ib.managedAccounts()
    if not any(a.startswith("D") for a in acct):
        ib.disconnect()
        raise SystemExit(f"connected account(s) {acct} do not look like paper — aborting")
    print(f"connected: {acct} on port {args.port}")

    rows, errors = [], {}
    try:
        for _, r in specs.iterrows():
            c = Contract(conId=int(r.conid))
            try:
                ib.qualifyContracts(c)
                bars = ib.reqHistoricalData(
                    c, endDateTime="", durationStr=f"{args.days} D",
                    barSizeSetting="1 hour", whatToShow="BID_ASK", useRTH=True,
                    formatDate=2, timeout=60,
                )
                df = util.df(bars)
            except Exception as e:  # noqa: BLE001
                errors[r.code] = str(e)
                df = None
            if df is None or df.empty:
                errors.setdefault(r.code, "no BID_ASK bars")
                print(f"  {r.code}: FAILED ({errors[r.code]})")
                time.sleep(args.pace)
                continue
            spread = (df["close"] - df["open"]).clip(lower=0)
            mid = (df["close"] + df["open"]) / 2
            med = float(spread.median())
            rows.append({
                "code": r.code, "front_contract": r.front_contract,
                "n_bars": len(df),
                "first_bar": str(df["date"].iloc[0]), "last_bar": str(df["date"].iloc[-1]),
                "spread_median_ticks": round(med / r.tick_size, 3),
                "spread_p90_ticks": round(float(spread.quantile(0.9)) / r.tick_size, 3),
                "spread_median_usd": round(med * r.multiplier, 4),
                "half_spread_bp": round(float((spread / mid).median()) / 2 * 1e4, 3),
                "as_of": date.today().isoformat(),
            })
            print(f"  {r.code}: {len(df)} bars, median {med / r.tick_size:.2f} ticks "
                  f"(${med * r.multiplier:.2f}), p90 {rows[-1]['spread_p90_ticks']:.2f} ticks")
            time.sleep(args.pace)
    finally:
        ib.disconnect()

    out = pd.DataFrame(rows)
    out.to_csv(OUT, index=False)
    print(f"\nwrote {len(out)} rows -> {OUT}; {len(errors)} errors")
    for k, v in errors.items():
        print(f"  ERROR {k}: {v}")


if __name__ == "__main__":
    main()
