"""S3 order-path test for the IBKR connection (docs/ibkr-connection-design.md).

Drives the platform's REAL order stack -- OrderManager + IBKRBroker + the
orders/fills/positions tables -- against a PAPER account, scripted rather
than strategy-driven. Requires: IB Gateway/TWS logged into a paper account
with Read-Only API off, `make infra` running, US market open.

Validates (design doc S3 / phase-7 P-3):
  1. 1-share MARKET buy -> fill event -> orders row FILLED, fills row
     present, positions row open with quantity 1.
  2. Far-below-market LIMIT buy -> cancel -> CANCELLED in DB, no fill row.
  3. get_positions() reconciles: broker's AAPL delta == DB position qty.
  4. Cleanup MARKET sell -> position closed in DB, broker back to baseline.

The independent side of the gate -- IBKR's own record -- is checked by a
human in Client Portal (IB Gateway has no blotter UI).

Config handling: oms.paper_mode is forced False IN-PROCESS ONLY (selects
IBKRBroker); config/default.yaml is not modified. The D3 live-port guard
still applies. Aborts before any order if the account is not DU-prefixed.

Uses the standard oms.ibkr_client_id (2) -- do not run while a live
strategy-runner process is connected.
"""

import asyncio
import os
import sys
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

sys.path.append(os.path.join(os.path.dirname(__file__), "../src"))

from axtrade.common import get_logger, load_config
from axtrade.common.db import DatabasePool
from axtrade.oms.manager import OrderManager
from axtrade.oms.repository import OrderRepository, PositionRepository
from axtrade.oms.types import Order, OrderSide, OrderStatus, OrderType

logger = get_logger("test_ibkr_order_path")

SYMBOL = "AAPL"
FILL_TIMEOUT_S = 90
CANCEL_TIMEOUT_S = 30


def now_tag() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


async def wait_for_status(
    repo: OrderRepository, order_id: UUID, statuses: set[OrderStatus], timeout_s: float
) -> OrderStatus | None:
    """Poll the DB until the order reaches one of the given statuses."""
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        order = await repo.get(order_id)
        if order and order.status in statuses:
            return order.status
        await asyncio.sleep(0.5)
    return None


async def broker_symbol_qty(broker, symbol: str) -> Decimal:
    """Signed quantity IBKR reports for symbol (0 if flat)."""
    for pos in await broker.get_positions():
        if pos.symbol == symbol:
            qty = pos.quantity
            return -qty if pos.side == "short" else qty
    return Decimal("0")


async def main() -> int:
    config = load_config()

    # In-process only: select IBKRBroker without touching config/default.yaml.
    config.oms.paper_mode = False

    port = config.gateway.ibkr.port
    print(f"S3 order-path test -- {config.gateway.ibkr.host}:{port}, "
          f"order clientId {config.oms.ibkr_client_id}")
    if port in (7496, 4001):
        print("ABORT: live port configured; this test is paper-only.")
        return 1

    strategy_id = f"s3_{now_tag()}"
    print(f"strategy_id for this run: {strategy_id}\n")

    results: dict[str, bool] = {}

    pool = DatabasePool(config.database)
    await pool.connect()
    order_repo = OrderRepository(pool)
    position_repo = PositionRepository(pool)

    manager = OrderManager(config, pool)

    fill_events: dict[UUID, asyncio.Event] = {}

    def on_fill(fill) -> None:
        ev = fill_events.get(fill.order_id)
        if ev:
            ev.set()

    manager.on_fill(on_fill)

    try:
        print("[setup] Connecting OrderManager (IBKRBroker)...")
        await manager.connect()
        broker = manager._broker
        ib = broker._ib

        # Hard safety gate: paper account only.
        accounts = ib.managedAccounts()
        if not accounts:
            await asyncio.sleep(1)
            accounts = ib.managedAccounts()
        account = accounts[0] if accounts else "?"
        print(f"[setup] Account: {account}")
        if not account.startswith("DU"):
            print("ABORT: not a paper (DU) account. No orders placed.")
            return 1

        # Delayed snapshot for a sane risk-check price.
        from ib_insync import Stock

        ib.reqMarketDataType({"delayed": 3, "live": 1}[config.gateway.ibkr.market_data_type])
        contract = (await ib.qualifyContractsAsync(Stock(SYMBOL, "SMART", "USD")))[0]
        ticker = ib.reqMktData(contract)
        # Delayed data can take >5s to start streaming; poll for any usable
        # price (last, then close, then bid/ask midpoint).
        last = None
        for _ in range(20):
            await asyncio.sleep(1)
            for candidate in (
                ticker.last,
                ticker.close,
                (ticker.bid + ticker.ask) / 2
                if ticker.bid == ticker.bid and ticker.ask == ticker.ask
                else float("nan"),
            ):
                if candidate == candidate and candidate is not None and candidate > 0:
                    last = candidate
                    break
            if last is not None:
                break
        ib.cancelMktData(contract)
        if last is None:
            print("ABORT: no price for AAPL (market closed?). Market orders need RTH.")
            return 1
        last = Decimal(str(last))
        manager.update_price(SYMBOL, float(last))
        print(f"[setup] {SYMBOL} last={last}")

        baseline_qty = await broker_symbol_qty(broker, SYMBOL)
        print(f"[setup] Broker baseline {SYMBOL} qty: {baseline_qty}\n")

        # --- Test A: MARKET buy 1 share -> fill -> DB rows ----------------
        print(f"[A] MARKET BUY 1 {SYMBOL}...")
        buy = Order(
            strategy_id=strategy_id, symbol=SYMBOL, side=OrderSide.BUY,
            quantity=Decimal("1"), order_type=OrderType.MARKET,
        )
        fill_events[buy.id] = asyncio.Event()
        await manager.submit_order(buy)
        try:
            await asyncio.wait_for(fill_events[buy.id].wait(), FILL_TIMEOUT_S)
        except asyncio.TimeoutError:
            pass

        status = await wait_for_status(order_repo, buy.id, {OrderStatus.FILLED}, 10)
        db_buy = await order_repo.get(buy.id)
        buy_fills = await order_repo.get_fills_for_order(buy.id)
        db_pos = await position_repo.get(strategy_id, SYMBOL)
        ok = (
            status == OrderStatus.FILLED
            and len(buy_fills) >= 1
            and sum(f.quantity for f in buy_fills) == Decimal("1")
            and db_pos is not None and db_pos.is_open and db_pos.quantity == Decimal("1")
        )
        results["market_buy_fill_db"] = ok
        if ok:
            f = buy_fills[0]
            print(f"  FILLED @ {f.price} (commission {f.commission}); "
                  f"orders/fills/positions rows all present and consistent.")
        else:
            print(f"  FAILED: status={db_buy.status if db_buy else None}, "
                  f"fills={len(buy_fills)}, position={db_pos}")

        # --- Test B: far LIMIT buy -> cancel -> no fill -------------------
        limit_price = (last * Decimal("0.5")).quantize(Decimal("0.01"))
        print(f"\n[B] LIMIT BUY 1 {SYMBOL} @ {limit_price} (far below market), then cancel...")
        lim = Order(
            strategy_id=strategy_id, symbol=SYMBOL, side=OrderSide.BUY,
            quantity=Decimal("1"), order_type=OrderType.LIMIT, limit_price=limit_price,
        )
        fill_events[lim.id] = asyncio.Event()
        await manager.submit_order(lim)
        await asyncio.sleep(3)  # let it rest on the (paper) book
        cancel_accepted = await manager.cancel_order(lim.id)
        print(f"  cancel request accepted by broker: {cancel_accepted}")
        status = await wait_for_status(order_repo, lim.id, {OrderStatus.CANCELLED}, CANCEL_TIMEOUT_S)
        lim_fills = await order_repo.get_fills_for_order(lim.id)
        ok = cancel_accepted and status == OrderStatus.CANCELLED and len(lim_fills) == 0
        results["limit_cancel_no_fill"] = ok
        print(f"  {'CANCELLED in DB, zero fills.' if ok else f'FAILED: status={status}, fills={len(lim_fills)}'}")

        # --- Test C: positions reconcile ----------------------------------
        print(f"\n[C] Reconciling get_positions() vs DB...")
        broker_qty = await broker_symbol_qty(broker, SYMBOL)
        db_pos = await position_repo.get(strategy_id, SYMBOL)
        db_qty = db_pos.quantity if db_pos and db_pos.is_open else Decimal("0")
        ok = (broker_qty - baseline_qty) == Decimal("1") == db_qty
        results["positions_reconcile"] = ok
        print(f"  broker {SYMBOL}: {broker_qty} (baseline {baseline_qty}), DB: {db_qty} -> "
              f"{'MATCH' if ok else 'MISMATCH'}")

        # --- Test D: cleanup sell -> flat ---------------------------------
        print(f"\n[D] Cleanup: MARKET SELL 1 {SYMBOL}...")
        sell = Order(
            strategy_id=strategy_id, symbol=SYMBOL, side=OrderSide.SELL,
            quantity=Decimal("1"), order_type=OrderType.MARKET,
        )
        fill_events[sell.id] = asyncio.Event()
        await manager.submit_order(sell)
        try:
            await asyncio.wait_for(fill_events[sell.id].wait(), FILL_TIMEOUT_S)
        except asyncio.TimeoutError:
            pass
        status = await wait_for_status(order_repo, sell.id, {OrderStatus.FILLED}, 10)
        db_pos = await position_repo.get(strategy_id, SYMBOL)
        end_qty = await broker_symbol_qty(broker, SYMBOL)
        ok = (
            status == OrderStatus.FILLED
            and db_pos is not None and not db_pos.is_open
            and end_qty == baseline_qty
        )
        results["cleanup_sell_flat"] = ok
        if ok:
            print(f"  Position closed (realized_pnl {db_pos.realized_pnl}); broker back to baseline.")
        else:
            print(f"  FAILED: status={status}, position={db_pos}, broker_qty={end_qty}")

    finally:
        await manager.disconnect()
        await pool.disconnect()

    print("\n" + "=" * 44)
    print("S3 ORDER-PATH TEST SUMMARY")
    print("=" * 44)
    all_pass = bool(results)
    for step, ok in results.items():
        if not ok:
            all_pass = False
        print(f"  {step:24s} {'PASS' if ok else 'FAIL'}")
    print("=" * 44)
    print(f"strategy_id: {strategy_id}")
    print("Now verify IBKR's own record in Client Portal (paper login):")
    print(f"  - two {SYMBOL} executions (BUY 1, SELL 1) and one cancelled LIMIT order")
    print("PASS: DB-side gate met" if all_pass else "FAIL: see steps above")
    return 0 if all_pass else 1


if __name__ == "__main__":
    logger.info("starting_ibkr_order_path_test")
    sys.exit(asyncio.run(main()))
