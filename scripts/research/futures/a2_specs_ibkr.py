"""T1 A2: assemble config/futures_specs.csv from the IBKR contract database.

Tier-2 scratch script (docs/t1-futures-plan.md §A2). The plan requires specs
from primary sources, not memory: CME's spec pages defeat scraping (JS-heavy,
timeouts), so the source is IBKR's contract database via reqContractDetails —
multiplier and minTick come from the exchange definition IBKR carries, and
conid + as_of record the exact provenance. source_url is a CME search
link (IBKR retired the per-conid public page — 302 to a generic listing,
observed 2026-08-31 — and CME spec pages 403 non-browser traffic, so no
per-product deep link can be verified from here). last_price is the front
contract's latest daily close. Margin is NOT collected: whatIfOrder returns
empty on this paper account (mirrors the live cash account's missing
futures trading permission) — fill margin_initial_usd from the TWS contract
dialog or CME margin page when the tradeable-subset math needs it.

Safety: paper ports only (7497/4002), clientId 94 (ad-hoc 9x range), aborts
unless the managed account looks like paper (D*). Contract-details and
historical-data requests only; no orders of any kind.

Usage:
    .venv/bin/python scripts/research/futures/a2_specs_ibkr.py [--port 7497]
"""

from __future__ import annotations

import argparse
import asyncio
import time
from urllib.parse import quote
from datetime import date
from pathlib import Path

import pandas as pd

# eventkit calls get_event_loop() at import; raises on Py3.12+ without a loop
asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB, Future  # noqa: E402

OUT = Path("config/futures_specs.csv")
PAPER_PORTS = {7497, 4002}
CLIENT_ID = 94  # 91/92 smoke tests, 93 contract fetcher

# code -> (ibkr symbol, exchange, name, sector, size_class)
UNIVERSE = {
    # equity index
    "ES":  ("ES",  "CME",    "E-mini S&P 500",            "equity", "full"),
    "MES": ("MES", "CME",    "Micro E-mini S&P 500",      "equity", "micro"),
    "NQ":  ("NQ",  "CME",    "E-mini Nasdaq-100",         "equity", "full"),
    "MNQ": ("MNQ", "CME",    "Micro E-mini Nasdaq-100",   "equity", "micro"),
    "RTY": ("RTY", "CME",    "E-mini Russell 2000",       "equity", "full"),
    "M2K": ("M2K", "CME",    "Micro E-mini Russell 2000", "equity", "micro"),
    "YM":  ("YM",  "CBOT",   "E-mini Dow ($5)",           "equity", "full"),
    "MYM": ("MYM", "CBOT",   "Micro E-mini Dow",          "equity", "micro"),
    # rates
    "ZT":  ("ZT",  "CBOT",   "2-Year T-Note",             "rates",  "full"),
    "ZF":  ("ZF",  "CBOT",   "5-Year T-Note",             "rates",  "full"),
    "ZN":  ("ZN",  "CBOT",   "10-Year T-Note",            "rates",  "full"),
    "ZB":  ("ZB",  "CBOT",   "30-Year T-Bond",            "rates",  "full"),
    "10Y": ("10Y", "CBOT",   "Micro 10-Year Yield",       "rates",  "micro"),
    # metals
    "GC":  ("GC",  "COMEX",  "Gold",                      "metals", "full"),
    "MGC": ("MGC", "COMEX",  "Micro Gold",                "metals", "micro"),
    "SI":  ("SI",  "COMEX",  "Silver",                    "metals", "full"),
    "SIL": ("SI",  "COMEX",  "Micro Silver (1000 oz)",    "metals", "micro"),
    "HG":  ("HG",  "COMEX",  "Copper",                    "metals", "full"),
    "MHG": ("MHG", "COMEX",  "Micro Copper",              "metals", "micro"),
    # energy
    "CL":  ("CL",  "NYMEX",  "WTI Crude Oil",             "energy", "full"),
    "MCL": ("MCL", "NYMEX",  "Micro WTI Crude Oil",       "energy", "micro"),
    "NG":  ("NG",  "NYMEX",  "Henry Hub Natural Gas",     "energy", "full"),
    # FX futures (spot FX excluded from T1 — no carry in spot)
    "6E":  ("EUR", "CME",    "Euro FX",                   "fx",     "full"),
    "M6E": ("M6E", "CME",    "Micro EUR/USD",             "fx",     "micro"),
    "6B":  ("GBP", "CME",    "British Pound",             "fx",     "full"),
    "M6B": ("M6B", "CME",    "Micro GBP/USD",             "fx",     "micro"),
    "6A":  ("AUD", "CME",    "Australian Dollar",         "fx",     "full"),
    "M6A": ("M6A", "CME",    "Micro AUD/USD",             "fx",     "micro"),
    "6J":  ("JPY", "CME",    "Japanese Yen",              "fx",     "full"),
}


def front_detail(ib: IB, symbol: str, exchange: str, trading_class: str):
    """Details for the nearest live contract of one trading class.

    One IBKR symbol can carry several books — symbol SI returns trading
    classes SI (5000 oz) and SIL (1000 oz micro) — so the class filter is
    what actually selects the product.
    """
    details = ib.reqContractDetails(
        Future(symbol=symbol, exchange=exchange, currency="USD")
    )
    details = [d for d in details if d.contract.tradingClass == trading_class]
    if not details:
        return None
    today = date.today().strftime("%Y%m%d")
    live = [d for d in details if d.contract.lastTradeDateOrContractMonth[:8] >= today]
    return min(
        live or details, key=lambda d: d.contract.lastTradeDateOrContractMonth
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7497)
    ap.add_argument("--pace", type=float, default=10.0)
    args = ap.parse_args()

    if args.port not in PAPER_PORTS:
        raise SystemExit(f"refusing port {args.port}: paper ports only {sorted(PAPER_PORTS)} "
                         "(no API against the live login — standing rule)")

    ib = IB()
    ib.connect(args.host, args.port, clientId=CLIENT_ID, timeout=20)
    acct = ib.managedAccounts()
    if not any(a.startswith("D") for a in acct):
        ib.disconnect()
        raise SystemExit(f"connected account(s) {acct} do not look like paper — aborting")
    print(f"connected: {acct} on port {args.port}")

    rows, errors = [], {}
    try:
        for code, (symbol, exchange, name, sector, size_class) in UNIVERSE.items():
            try:
                d = front_detail(ib, symbol, exchange, trading_class=code)
            except Exception as e:  # noqa: BLE001
                d = None
                errors[code] = str(e)
            if d is None:
                errors.setdefault(code, "no contract details")
                print(f"  {code}: FAILED ({errors[code]})")
                continue
            c = d.contract
            multiplier = float(c.multiplier)
            tick = float(d.minTick)

            last_price = None
            try:
                bars = ib.reqHistoricalData(
                    c, endDateTime="", durationStr="5 D", barSizeSetting="1 day",
                    whatToShow="TRADES", useRTH=True, formatDate=1,
                )
                if bars:
                    last_price = float(bars[-1].close)
            except Exception as e:  # noqa: BLE001
                errors[f"{code}/price"] = str(e)

            rows.append({
                "code": code, "name": name, "exchange": exchange,
                "sector": sector, "size_class": size_class,
                "multiplier": multiplier, "tick_size": tick,
                "tick_value_usd": multiplier * tick,
                "last_price": last_price,
                "front_contract": c.localSymbol, "conid": c.conId,
                "source_url": f"https://www.cmegroup.com/search.html?q={quote(name)}",
                "as_of": date.today().isoformat(),
            })
            print(f"  {code}: {c.localSymbol} tc {c.tradingClass} mult {multiplier} "
                  f"tick {tick} tickval {multiplier * tick:.4f} last {last_price}")
            time.sleep(args.pace)
    finally:
        ib.disconnect()

    df = pd.DataFrame(rows)
    OUT.parent.mkdir(exist_ok=True)
    df.to_csv(OUT, index=False)
    print(f"\nwrote {len(df)} rows -> {OUT}; {len(errors)} errors")
    for k, v in errors.items():
        print(f"  ERROR {k}: {v}")


if __name__ == "__main__":
    main()
