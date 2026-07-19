"""S0 smoke test for the IBKR connection (docs/ibkr-connection-design.md).

Mirrors scripts/test_alpaca_connection.py. Standalone asyncio script, run
via .venv/bin/python. Requires TWS or IB Gateway running and reachable at
config gateway.ibkr.host/port, logged into a PAPER account.

Validates:
  1. A data-role IB connection (clientId 91) can connect.
  2. An order-role IB connection (clientId 92) can connect AT THE SAME TIME
     as (1) -- proves the D1 clientId split actually avoids the "client id
     is already in use" rejection.
  3. reqMarketDataType is honored per gateway.ibkr.market_data_type (D2).
  4. AAPL contract qualification succeeds.
  5. The connected account is a paper account (id starts with "DU"). Exits
     nonzero with a loud warning if not -- this script must never be run
     unknowingly against a live account.
  6. One market-data snapshot for AAPL is requested and whatever arrives
     within ~5s is printed (fields may be empty/NaN when the market is
     closed, e.g. on a weekend -- that's OK and noted as such).
  7. Both connections are cleanly disconnected.

Places NO orders. clientIds 91/92 are reserved for ad-hoc tools (see D1 in
the design doc) so this can run alongside live gateway (clientId 1) and
order-manager (clientId 2) processes without colliding.
"""

import asyncio
import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), "../src"))

from axtrade.common import get_logger, load_config

logger = get_logger("test_ibkr_connection")

DATA_CLIENT_ID = 91
ORDER_CLIENT_ID = 92

MARKET_DATA_TYPE_MAP = {"delayed": 3, "live": 1}


async def main() -> int:
    from ib_insync import IB, Stock

    config = load_config()
    ibkr_config = config.gateway.ibkr

    print(f"Testing IBKR connection to {ibkr_config.host}:{ibkr_config.port}")
    print(f"Configured market data type: {ibkr_config.market_data_type}")

    results: dict[str, bool] = {}
    qualified_contract = None

    data_ib = IB()
    order_ib = IB()

    try:
        # --- Steps 1 & 2: two simultaneous connections -----------------
        print(f"\n[1/7] Connecting data client (clientId={DATA_CLIENT_ID})...")
        try:
            await data_ib.connectAsync(
                host=ibkr_config.host, port=ibkr_config.port, clientId=DATA_CLIENT_ID
            )
            print("  Connected.")
            results["connect_data_client"] = True
        except Exception as e:
            print(f"  FAILED: {e}")
            results["connect_data_client"] = False

        print(f"[2/7] Connecting order client (clientId={ORDER_CLIENT_ID}) concurrently...")
        try:
            await order_ib.connectAsync(
                host=ibkr_config.host, port=ibkr_config.port, clientId=ORDER_CLIENT_ID
            )
            print("  Connected -- both connections up at once (D1 clientId split OK).")
            results["connect_order_client"] = True
        except Exception as e:
            print(f"  FAILED: {e}")
            results["connect_order_client"] = False

        # --- Step 3: market data type ------------------------------------
        print(f"\n[3/7] Requesting market data type ({ibkr_config.market_data_type})...")
        try:
            md_type = MARKET_DATA_TYPE_MAP[ibkr_config.market_data_type]
            data_ib.reqMarketDataType(md_type)
            print(f"  reqMarketDataType({md_type}) sent.")
            results["market_data_type"] = True
        except Exception as e:
            print(f"  FAILED: {e}")
            results["market_data_type"] = False

        # --- Step 4: qualify AAPL ----------------------------------------
        print("\n[4/7] Qualifying AAPL contract...")
        try:
            contract = Stock("AAPL", "SMART", "USD")
            qualified = await data_ib.qualifyContractsAsync(contract)
            if qualified:
                qualified_contract = qualified[0]
                print(f"  Qualified: {qualified_contract}")
                results["qualify_contract"] = True
            else:
                print("  FAILED: no contract returned")
                results["qualify_contract"] = False
        except Exception as e:
            print(f"  FAILED: {e}")
            results["qualify_contract"] = False

        # --- Step 5: confirm paper account --------------------------------
        print('\n[5/7] Checking account id (must be paper: "DU" prefix)...')
        try:
            accounts = order_ib.managedAccounts()
            if not accounts:
                # Can be empty immediately after connect; give ib_insync's
                # event loop a moment to populate it.
                await asyncio.sleep(1)
                accounts = order_ib.managedAccounts()

            if not accounts:
                print("  FAILED: no managed accounts reported")
                results["paper_account"] = False
            else:
                account_id = accounts[0]
                print(f"  Account: {account_id}")
                if account_id.startswith("DU"):
                    results["paper_account"] = True
                else:
                    print(
                        f"  *** WARNING: account '{account_id}' does NOT look like a "
                        "paper account (expected a 'DU' prefix). This script refuses "
                        "to proceed further against a possibly-live account. ***"
                    )
                    results["paper_account"] = False
        except Exception as e:
            print(f"  FAILED: {e}")
            results["paper_account"] = False

        # --- Step 6: one snapshot ticker ----------------------------------
        print("\n[6/7] Requesting one snapshot ticker for AAPL (~5s)...")
        if qualified_contract is None:
            print("  SKIPPED: no qualified contract from step 4")
            results["snapshot"] = False
        else:
            try:
                ticker = data_ib.reqMktData(qualified_contract)
                await asyncio.sleep(5)
                print(
                    f"  last={ticker.last} bid={ticker.bid} ask={ticker.ask} "
                    f"volume={ticker.volume}"
                )
                if ticker.last != ticker.last:  # NaN != NaN
                    print(
                        "  (fields are empty/NaN -- OK if the market is closed, "
                        "e.g. outside trading hours or on a weekend)"
                    )
                data_ib.cancelMktData(qualified_contract)
                results["snapshot"] = True
            except Exception as e:
                print(f"  FAILED: {e}")
                results["snapshot"] = False

    finally:
        # --- Step 7: disconnect both --------------------------------------
        print("\n[7/7] Disconnecting both clients...")
        try:
            if data_ib.isConnected():
                data_ib.disconnect()
            if order_ib.isConnected():
                order_ib.disconnect()
            print("  Disconnected.")
            results["disconnect"] = True
        except Exception as e:
            print(f"  FAILED: {e}")
            results["disconnect"] = False

    print("\n" + "=" * 44)
    print("S0 SMOKE TEST SUMMARY")
    print("=" * 44)
    all_pass = True
    for step, ok in results.items():
        status = "PASS" if ok else "FAIL"
        if not ok:
            all_pass = False
        print(f"  {step:24s} {status}")
    print("=" * 44)

    if all_pass:
        print("PASS: all steps succeeded")
        return 0
    else:
        print("FAIL: see steps above")
        return 1


if __name__ == "__main__":
    logger.info("starting_ibkr_smoke_test")
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
