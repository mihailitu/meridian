"""T1 A5: merge specs + empirical spreads + IBKR fees into config/futures_costs.csv.

Tier-2 scratch script (docs/t1-futures-plan.md §A5). Offline, no broker
connection. Inputs:

- config/futures_specs.csv   (A2: multiplier, tick, last_price)
- config/futures_spreads.csv (a5_spreads_ibkr.py: BID_ASK-bar spread stats)
- config/futures_fees_ibkr.csv (hand-transcribed 2026-08-31 from IBKR's
  commission page — IBKR Pro, <=1,000 contracts/month tier, where Fixed and
  Tiered coincide — and the per-exchange fee-recovery pages, non-member
  tier; source_url per row)

Round-trip cost model per contract (one entry + one exit, marketable):
    rt_fees_usd  = 2 * (commission + exchange_fee + regulatory_fee)
    rt_cost_usd  = rt_fees_usd + spread_median_usd     # cross the spread twice = one full spread
    rt_cost_bp   = rt_cost_usd / (last_price * multiplier) * 1e4

Usage:
    .venv/bin/python scripts/research/futures/a5_cost_table.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

SPECS = Path("config/futures_specs.csv")
SPREADS = Path("config/futures_spreads.csv")
FEES = Path("config/futures_fees_ibkr.csv")
OUT = Path("config/futures_costs.csv")


def main() -> None:
    specs = pd.read_csv(SPECS)
    spreads = pd.read_csv(SPREADS)
    fees = pd.read_csv(FEES)

    df = specs[["code", "sector", "size_class", "multiplier", "tick_size", "last_price"]]
    df = df.merge(spreads[["code", "front_contract", "n_bars", "spread_median_ticks",
                           "spread_p90_ticks", "spread_median_usd", "half_spread_bp"]],
                  on="code", how="left")
    df = df.merge(fees[["code", "commission_usd", "exchange_fee_usd", "regulatory_fee_usd",
                        "fee_note"]], on="code", how="left")

    df["notional_usd"] = df["last_price"] * df["multiplier"]
    df["rt_fees_usd"] = 2 * (df["commission_usd"] + df["exchange_fee_usd"]
                             + df["regulatory_fee_usd"])
    df["rt_cost_usd"] = df["rt_fees_usd"] + df["spread_median_usd"]
    df["rt_cost_bp"] = df["rt_cost_usd"] / df["notional_usd"] * 1e4
    df["as_of"] = spreads["as_of"].iloc[0]

    df.to_csv(OUT, index=False)
    pd.set_option("display.width", 200)
    cols = ["code", "sector", "size_class", "notional_usd", "spread_median_ticks",
            "spread_median_usd", "rt_fees_usd", "rt_cost_usd", "rt_cost_bp"]
    print(df.sort_values(["sector", "notional_usd"])[cols]
          .to_string(index=False, float_format=lambda x: f"{x:,.3g}"))
    print(f"\nwrote {len(df)} rows -> {OUT}")


if __name__ == "__main__":
    main()
