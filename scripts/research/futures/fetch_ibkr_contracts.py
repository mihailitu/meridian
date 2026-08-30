"""T1 A-lite: fetch per-contract daily futures bars from IBKR (paper TWS).

Tier-2 scratch script (docs/t1-futures-plan.md, "A-lite on IBKR recent
data"). Pulls individual contract histories (including expired contracts —
IBKR retains them ~2 years past expiry) so the A3 continuous-series builder
has real, provable ingredients for the recent window.

Safety: connects ONLY to paper ports (7497 TWS / 4002 Gateway) with an
ad-hoc clientId from the 9x range (docs/ibkr-connection-design.md). Refuses
live ports 7496/4001 unconditionally — same stance as oms.IBKRBroker. Places
no orders; historical data requests only.

Output: data/futures/ibkr/{root}/{localSymbol}.parquet (date, open, high,
low, close, volume, average, barCount) + data/futures/ibkr/manifest.json
recording per-contract coverage and any permission errors.

Usage:
    .venv/bin/python scripts/research/futures/fetch_ibkr_contracts.py \
        [--roots CL ES GC ZN 6E] [--port 7497] [--pace 10]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path

# eventkit (ib_insync dep) calls get_event_loop() at import time, which
# raises on Python 3.12+ when no loop exists in the main thread
asyncio.set_event_loop(asyncio.new_event_loop())

from ib_insync import IB, Contract, Future, util  # noqa: E402

OUT = Path("data/futures/ibkr")
PAPER_PORTS = {7497, 4002}
CLIENT_ID = 93  # ad-hoc tool range 9x; 91/92 used by connection smoke tests

# root -> (exchange, currency); full-size contracts (data leg, best history)
DEFAULT_ROOTS = {
    "CL": ("NYMEX", "USD"),
    "ES": ("CME", "USD"),
    "GC": ("COMEX", "USD"),
    "ZN": ("CBOT", "USD"),
    "6E": ("CME", "USD"),
}


def eligible_contracts(ib: IB, root: str, exchange: str, currency: str) -> list[Contract]:
    """All contracts for `root` whose expiry falls in the retrievable window."""
    spec = Future(symbol=root, exchange=exchange, currency=currency, includeExpired=True)
    details = ib.reqContractDetails(spec)
    horizon_lo = date.today() - timedelta(days=2 * 365)
    horizon_hi = date.today() + timedelta(days=400)
    out = []
    for d in details:
        c = d.contract
        exp = datetime.strptime(c.lastTradeDateOrContractMonth[:8], "%Y%m%d").date()
        if horizon_lo <= exp <= horizon_hi:
            c.includeExpired = True
            out.append(c)
    return sorted(out, key=lambda c: c.lastTradeDateOrContractMonth)


def fetch_contract(ib: IB, c: Contract) -> "util.df":
    exp = datetime.strptime(c.lastTradeDateOrContractMonth[:8], "%Y%m%d").date()
    end = "" if exp >= date.today() else exp.strftime("%Y%m%d") + " 23:59:59 US/Central"
    bars = ib.reqHistoricalData(
        c, endDateTime=end, durationStr="2 Y", barSizeSetting="1 day",
        whatToShow="TRADES", useRTH=True, formatDate=1,
    )
    return util.df(bars)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", nargs="+", default=list(DEFAULT_ROOTS))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=7497)
    ap.add_argument("--pace", type=float, default=10.0,
                    help="seconds between historical requests (IBKR pacing)")
    args = ap.parse_args()

    if args.port not in PAPER_PORTS:
        raise SystemExit(f"refusing port {args.port}: paper ports only {sorted(PAPER_PORTS)} "
                         "(no API against the live login — standing rule)")

    ib = IB()
    ib.connect(args.host, args.port, clientId=CLIENT_ID, timeout=20)
    acct = ib.managedAccounts()
    if not any(a.startswith("D") for a in acct):  # paper accounts are DU*/DF*
        ib.disconnect()
        raise SystemExit(f"connected account(s) {acct} do not look like paper — aborting")
    print(f"connected: {acct} on port {args.port}")

    manifest: dict = {"fetched_at": datetime.now().isoformat(), "account": acct,
                      "contracts": {}, "errors": {}}
    try:
        for root in args.roots:
            exchange, currency = DEFAULT_ROOTS.get(root, ("CME", "USD"))
            try:
                contracts = eligible_contracts(ib, root, exchange, currency)
            except Exception as e:  # noqa: BLE001 — recorded, not fatal
                manifest["errors"][root] = f"contract lookup: {e}"
                continue
            print(f"{root}: {len(contracts)} contracts in window")
            (OUT / root).mkdir(parents=True, exist_ok=True)
            for c in contracts:
                try:
                    df = fetch_contract(ib, c)
                except Exception as e:  # noqa: BLE001
                    manifest["errors"][f"{root}/{c.localSymbol}"] = str(e)
                    time.sleep(args.pace)
                    continue
                if df is None or df.empty:
                    manifest["errors"][f"{root}/{c.localSymbol}"] = "no bars returned"
                else:
                    path = OUT / root / f"{c.localSymbol}.parquet"
                    df.to_parquet(path)
                    manifest["contracts"][f"{root}/{c.localSymbol}"] = {
                        "expiry": c.lastTradeDateOrContractMonth,
                        "rows": len(df),
                        "first": str(df["date"].iloc[0]),
                        "last": str(df["date"].iloc[-1]),
                    }
                    print(f"  {c.localSymbol}: {len(df)} bars "
                          f"{df['date'].iloc[0]} → {df['date'].iloc[-1]}")
                time.sleep(args.pace)
    finally:
        ib.disconnect()

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    ok, err = len(manifest["contracts"]), len(manifest["errors"])
    print(f"done: {ok} contracts saved, {err} errors -> {OUT / 'manifest.json'}")


if __name__ == "__main__":
    main()
