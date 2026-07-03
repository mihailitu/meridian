"""End-to-end integration test for the live-paper trading path.

Exercises the real service classes -- GatewayService (MockAdapter) ->
AggregatorService -> StrategyRunner (buy_hold) -> PaperBroker -- wired
together with real Redis Streams and a real TimescaleDB, the same way
`make run` + `make run-aggregator` + `make run-strategy` would, minus the
process boundaries. The fulltest harness (src/axtrade/fulltest/) already
proves the replay path end-to-end; nothing else proves the live-paper path
actually works, which is what this test is for (audit C2).

Isolation: runs against Redis db=2 and database `axtrade_itest`, never the
live db=0 / `axtrade` (fulltest owns db=1 / `axtrade_backtest`). See
`_build_itest_config` and the `itest_config` fixture.
"""

import asyncio
import copy
from typing import Optional

import asyncpg
import pytest
import redis.asyncio as aioredis

from axtrade.aggregator.service import AggregatorService
from axtrade.common import (
    Config,
    DatabaseConfig,
    MockConfig,
    StrategyInstanceConfig,
    SymbolConfig,
    load_config,
)
from axtrade.fulltest.isolation import BacktestInfrastructure
from axtrade.gateway.service import GatewayService
from axtrade.strategies.runner import StrategyRunner

pytestmark = pytest.mark.integration

ITEST_REDIS_DB = 2  # fulltest owns db=1; live is db=0
ITEST_DB_NAME = "axtrade_itest"
STRATEGY_ID = "buy_hold-it"
SYMBOLS = [
    SymbolConfig(symbol="AAPL", base_price=100.0),
    SymbolConfig(symbol="MSFT", base_price=200.0),
]

POLL_INTERVAL_S = 2.0
POLL_TIMEOUT_S = 150.0  # first 1m bar can take up to ~65s to close


async def _infra_reachable(base_config: Config) -> bool:
    """Quick reachability probe (~2s) so the suite skips cleanly instead of
    hanging when docker infra (make infra) isn't running."""
    try:
        client = aioredis.Redis(
            host=base_config.redis.host,
            port=base_config.redis.port,
        )
        await asyncio.wait_for(client.ping(), timeout=2.0)
        await client.aclose()
    except Exception:
        return False

    try:
        conn = await asyncio.wait_for(
            asyncpg.connect(
                host=base_config.database.host,
                port=base_config.database.port,
                database=base_config.database.database,
                user=base_config.database.user,
                password=base_config.database.password,
            ),
            timeout=2.0,
        )
        await conn.close()
    except Exception:
        return False

    return True


def _build_itest_config(base_config: Config) -> Config:
    """Isolated config: real Redis/TimescaleDB connection settings from
    config/default.yaml, but pointed at db=2 / axtrade_itest and namespaced
    stream/consumer-group/control-channel names so a stray live gateway or
    strategy runner listening on the shared pubsub channels can't see this
    run's control traffic either.
    """
    config = copy.deepcopy(base_config)

    config.redis.db = ITEST_REDIS_DB
    config.redis.stream_prefix = "it:stream:ticks"
    config.database.database = ITEST_DB_NAME

    config.aggregator.intervals = ["1m"]
    config.aggregator.source_stream = "it:stream:ticks:us"
    config.aggregator.consumer_group = "it_aggregator"
    config.aggregator.bar_stream_prefix = "it:stream:bars"

    config.strategies.bar_stream = "it:stream:bars:1m:us"
    config.strategies.consumer_group = "it_strategies"
    config.strategies.control_channel = "it:axtrade:strategy:control"
    config.gateway.control_channel = "it:axtrade:gateway:control"

    config.gateway.adapter = "mock"
    # tick_interval_ms kept small so a bar has plenty of ticks; volatility
    # lowered from the 0.001 default so the fill-price sanity check below
    # holds comfortably even in the (wall-clock-dependent, hence not fully
    # deterministic) worst case of ~800 ticks before the first bar closes.
    config.gateway.mock = MockConfig(
        tick_interval_ms=75, volatility=0.0002, seed=20260703
    )
    config.gateway.symbols = list(SYMBOLS)

    config.discovery.enabled = False
    config.discovery.auto_subscribe = False

    config.oms.paper_mode = True

    config.strategies.enabled = [
        StrategyInstanceConfig(
            type="buy_hold",
            id=STRATEGY_ID,
            enabled=True,
            config={
                "position_size": 10,
                "allowed_symbols": [s.symbol for s in SYMBOLS],
            },
        )
    ]

    return config


async def _truncate_itest_tables(db_config: DatabaseConfig) -> None:
    """Drop this run's rows so a rerun starts clean (BacktestInfrastructure
    already truncates on setup(), but the fixture also does it on teardown
    per spec, to leave a clean DB behind even if a run is interrupted)."""
    conn = await asyncpg.connect(
        host=db_config.host,
        port=db_config.port,
        database=ITEST_DB_NAME,
        user=db_config.user,
        password=db_config.password,
    )
    try:
        for table in ("fills", "orders", "positions", "bars"):
            try:
                await conn.execute(f"TRUNCATE {table} CASCADE")
            except Exception:
                pass
    finally:
        await conn.close()


@pytest.fixture
async def itest_config():
    """Isolated config + infra lifecycle: creates/prepares axtrade_itest and
    flushes Redis db=2 before the test, flushes+truncates after."""
    base_config = load_config()

    if not await _infra_reachable(base_config):
        pytest.skip("integration infra not running (make infra)")

    config = _build_itest_config(base_config)

    infra = BacktestInfrastructure(
        db_config=base_config.database,
        redis_config=config.redis,
        backtest_db_name=ITEST_DB_NAME,
    )
    await infra.setup()

    try:
        yield config
    finally:
        await infra.teardown()  # flushes redis db=2
        await _truncate_itest_tables(base_config.database)


async def _fetch_state(db_dsn_config: DatabaseConfig) -> dict:
    """Snapshot the bits of DB state the polling loop and assertions need."""
    conn = await asyncpg.connect(
        host=db_dsn_config.host,
        port=db_dsn_config.port,
        database=ITEST_DB_NAME,
        user=db_dsn_config.user,
        password=db_dsn_config.password,
    )
    try:
        bars = await conn.fetch(
            "SELECT symbol, close FROM bars WHERE interval = '1m' ORDER BY symbol, time"
        )
        orders = await conn.fetch(
            "SELECT symbol, side, status FROM orders WHERE strategy_id = $1",
            STRATEGY_ID,
        )
        fills = await conn.fetch(
            "SELECT symbol, side FROM fills WHERE strategy_id = $1",
            STRATEGY_ID,
        )
        positions = await conn.fetch(
            "SELECT symbol, quantity, avg_entry_price FROM positions "
            "WHERE strategy_id = $1 AND closed_at IS NULL",
            STRATEGY_ID,
        )
    finally:
        await conn.close()

    return {
        "bars": bars,
        "orders": orders,
        "fills": fills,
        "positions": positions,
    }


def _conditions_met(state: dict) -> bool:
    symbols = {s.symbol for s in SYMBOLS}

    bar_symbols = {r["symbol"] for r in state["bars"]}
    if not symbols.issubset(bar_symbols):
        return False

    buy_orders = {
        r["symbol"] for r in state["orders"]
        if r["side"] == "buy" and r["status"] == "filled"
    }
    if not symbols.issubset(buy_orders):
        return False

    fill_symbols = {r["symbol"] for r in state["fills"] if r["side"] == "buy"}
    if not symbols.issubset(fill_symbols):
        return False

    position_symbols = {r["symbol"] for r in state["positions"]}
    if not symbols.issubset(position_symbols):
        return False

    return True


async def test_live_paper_pipeline_end_to_end(itest_config):
    """Run gateway -> aggregator -> strategy runner -> PaperBroker for real
    and verify a bar closes, buy_hold buys once per symbol, and the fill
    lands in positions/orders/fills."""
    config = itest_config

    gateway = GatewayService(config)
    aggregator = AggregatorService(config)
    strategy_runner = StrategyRunner(config)

    gateway_task = asyncio.create_task(gateway.start())
    aggregator_task = asyncio.create_task(aggregator.start())
    strategy_task = asyncio.create_task(strategy_runner.start())

    service_tasks = [gateway_task, aggregator_task, strategy_task]

    try:
        # Poll instead of sleeping blind: the first 1m bar only closes once
        # a tick crosses a wall-clock minute boundary, so this can legitimately
        # take up to ~65s.
        state: Optional[dict] = None
        elapsed = 0.0
        while elapsed < POLL_TIMEOUT_S:
            for task in service_tasks:
                if task.done() and task.exception() is not None:
                    raise task.exception()

            state = await _fetch_state(config.database)
            if _conditions_met(state):
                break
            await asyncio.sleep(POLL_INTERVAL_S)
            elapsed += POLL_INTERVAL_S
        else:
            state = await _fetch_state(config.database)

        assert state is not None
        assert _conditions_met(state), (
            f"Pipeline did not reach the expected state within "
            f"{POLL_TIMEOUT_S}s: {state}"
        )

        symbols = {s.symbol for s in SYMBOLS}
        base_prices = {s.symbol: s.base_price for s in SYMBOLS}

        # Exactly one BUY per symbol -- buy_hold must never re-buy, even if
        # a second bar happens to close within the polling window.
        buy_orders_by_symbol: dict[str, int] = {}
        for row in state["orders"]:
            if row["side"] == "buy":
                buy_orders_by_symbol[row["symbol"]] = (
                    buy_orders_by_symbol.get(row["symbol"], 0) + 1
                )
        for symbol in symbols:
            assert buy_orders_by_symbol.get(symbol) == 1, (
                f"expected exactly one BUY order for {symbol}, "
                f"got {buy_orders_by_symbol.get(symbol, 0)}: {state['orders']}"
            )

        # Positions opened with a plausible entry price. Fill price is
        # close * 1.001 (default 10bps slippage) -- checked loosely since
        # the mock random walk length depends on wall-clock alignment, not
        # just the RNG seed.
        for row in state["positions"]:
            if row["symbol"] not in symbols:
                continue
            entry_price = float(row["avg_entry_price"])
            base_price = base_prices[row["symbol"]]
            assert entry_price > 0
            assert abs(entry_price - base_price) / base_price < 0.05, (
                f"{row['symbol']} entry price {entry_price} implausibly far "
                f"from base price {base_price}"
            )

    finally:
        # Shut down in the same order the fulltest orchestrator does:
        # aggregator, then strategy runner, then gateway.
        for svc in (aggregator, strategy_runner, gateway):
            try:
                await svc.stop()
            except Exception:
                pass

        for task in service_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    # No exceptions should have surfaced from any service task.
    for task in service_tasks:
        assert task.cancelled() or task.exception() is None, (
            f"service task raised: {task.exception()}"
        )
