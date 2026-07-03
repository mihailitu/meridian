"""Main orchestrator for full system backtest."""

import asyncio
import copy
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import redis.asyncio as aioredis

from axtrade.common import (
    BarRepository,
    Config,
    DatabasePool,
    StrategyInstanceConfig,
    SymbolConfig,
    get_logger,
    load_config,
)
from axtrade.aggregator.service import AggregatorService
from axtrade.discovery.service import DiscoveryService
from axtrade.indicators import calculate_rsi, calculate_sma
from axtrade.gateway.control import GatewayControlPublisher
from axtrade.gateway.service import GatewayService
from axtrade.strategies import STRATEGY_TYPES
from axtrade.strategies.runner import StrategyRunner

from .data import download_historical_alpaca
from .discovery import BacktestDiscoveryRunner
from .isolation import BacktestInfrastructure
from .replay_adapter import ReplayAdapter
from .report import ReportGenerator, format_json_report, format_text_report
from .types import FullBacktestConfig, FullBacktestResult
from .universe import SP500SymbolProvider

logger = get_logger("fulltest.orchestrator")


def daily_rows_from_minute_df(df: pd.DataFrame, symbol: str) -> list[tuple]:
    """Aggregate a 1m OHLCV frame into daily bar rows for the bars table.

    Each daily bar is stamped with the day's last minute-bar timestamp, so a
    query bounded by the sim clock only sees a day once it has fully closed.
    SMA-20 / RSI-14 are computed over the daily closes because the discovery
    screeners read them off the bar row.

    Returns rows in bulk_insert_bars order:
    (time, symbol, open, high, low, close, volume, sma_20, rsi_14)
    """
    ts = df["timestamp"]
    if ts.dt.tz is None:
        ts = ts.dt.tz_localize("UTC")
    df = df.assign(timestamp=ts).sort_values("timestamp")

    grouped = df.groupby(df["timestamp"].dt.date, sort=True)
    daily = pd.DataFrame(
        {
            "timestamp": grouped["timestamp"].last(),
            "open": grouped["open"].first(),
            "high": grouped["high"].max(),
            "low": grouped["low"].min(),
            "close": grouped["close"].last(),
            "volume": grouped["volume"].sum(),
        }
    )

    closes = [float(c) for c in daily["close"]]
    rows = []
    for i in range(len(daily)):
        # 100 closes are plenty for Wilder smoothing to converge; a full
        # prefix would make seeding a year of 1500 symbols quadratic.
        window = closes[max(0, i - 99) : i + 1]
        sma_v = calculate_sma(window, 20)
        rsi_v = calculate_rsi(window, 14)
        rows.append(
            (
                daily["timestamp"].iloc[i].to_pydatetime(),
                symbol,
                Decimal(str(float(daily["open"].iloc[i]))),
                Decimal(str(float(daily["high"].iloc[i]))),
                Decimal(str(float(daily["low"].iloc[i]))),
                Decimal(str(float(daily["close"].iloc[i]))),
                int(daily["volume"].iloc[i]),
                Decimal(str(sma_v)) if sma_v is not None else None,
                Decimal(str(rsi_v)) if rsi_v is not None else None,
            )
        )
    return rows


async def _consumer_lag(
    client: "aioredis.Redis", stream: str, group: str
) -> Optional[int]:
    """Undelivered-entry count for a consumer group, or None if unknowable
    (stream/group missing, or pre-7.0 Redis without the lag field)."""
    try:
        groups = await client.xinfo_groups(stream)
    except aioredis.ResponseError:
        return None
    ginfo = next((g for g in groups if g.get("name") == group), None)
    if ginfo is None:
        return None
    return ginfo.get("lag")


async def _drain_stream(
    client: "aioredis.Redis",
    stream: str,
    group: str,
    label: str,
    poll_seconds: float = 0.5,
    stall_timeout: float = 30.0,
) -> None:
    """Wait until `group` has fully consumed `stream`.

    Drained means the group's last-delivered-id has reached the stream's
    last-generated-id and no delivered message is pending acknowledgement
    (the consumers ack only after processing). Bails out with a warning if
    the consumer stops making progress, so a dead consumer can't hang the
    run forever.
    """
    last_seen: Optional[str] = None
    stalled = 0.0
    logged = 0.0
    while True:
        try:
            info = await client.xinfo_stream(stream)
            groups = await client.xinfo_groups(stream)
        except aioredis.ResponseError:
            return  # stream never created — nothing was produced
        target = info.get("last-generated-id")
        ginfo = next((g for g in groups if g.get("name") == group), None)
        if ginfo is None:
            return  # consumer group never attached
        delivered = ginfo.get("last-delivered-id")
        pending = ginfo.get("pending", 0)

        if delivered == target and not pending:
            logger.info("Stream drained", stream=label)
            return

        if delivered == last_seen:
            stalled += poll_seconds
            if stalled >= stall_timeout:
                logger.warning(
                    "Stream drain stalled, giving up",
                    stream=label,
                    delivered=str(delivered),
                    target=str(target),
                    pending=pending,
                )
                return
        else:
            stalled = 0.0
            last_seen = delivered

        logged += poll_seconds
        if logged >= 15.0:
            logged = 0.0
            logger.info(
                "Draining stream",
                stream=label,
                delivered=str(delivered),
                target=str(target),
                pending=pending,
            )
        await asyncio.sleep(poll_seconds)


class FullBacktestOrchestrator:
    """Coordinates a full system backtest.

    Runs all services in-process within a single asyncio event loop,
    using real Redis Streams and TimescaleDB for data flow with
    isolated databases to avoid polluting production.
    """

    def __init__(
        self,
        bt_config: FullBacktestConfig,
        base_config: Optional[Config] = None,
    ):
        self._bt_config = bt_config
        self._base_config = base_config or load_config()

    async def run(self) -> FullBacktestResult:
        """Execute the full backtest.

        Returns:
            FullBacktestResult with all metrics
        """
        start_time = datetime.now(timezone.utc)
        logger.info(
            "Starting full system backtest",
            start=str(self._bt_config.start),
            end=str(self._bt_config.end),
            symbols=len(self._bt_config.symbols),
        )

        # Step 1: Ensure historical data exists (unless skip_download)
        if not self._bt_config.skip_download:
            await self._ensure_data()
        else:
            logger.info("Skipping data download (using existing data)")

        # Step 2: Set up isolated infrastructure
        config = self._build_isolated_config()
        infra = BacktestInfrastructure(
            db_config=self._base_config.database,
            redis_config=config.redis,
            backtest_db_name=self._bt_config.backtest_db_name,
        )
        await infra.setup()

        try:
            # Step 2.5: Pre-seed universe bars if discovery is enabled
            if self._bt_config.discovery_enabled:
                await self._preseed_universe_bars(config)

            # Step 3: Create and run services
            result = await self._run_services(config)
        finally:
            # Step 4: Clean up Redis (DB kept)
            await infra.teardown()

        # Step 5: Generate report
        report_gen = ReportGenerator(
            db_config=self._base_config.database,
            backtest_db_name=self._bt_config.backtest_db_name,
        )
        result = await report_gen.generate(self._bt_config, result)

        result.start_time = start_time
        result.end_time = datetime.now(timezone.utc)

        # Print report
        if self._bt_config.report_format == "json":
            report_text = format_json_report(result)
        else:
            report_text = format_text_report(result)

        print(report_text)

        # Save report to file
        output_dir = Path(self._bt_config.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = start_time.astimezone().strftime("%Y%m%d_%H%M%S")
        report_ext = "json" if self._bt_config.report_format == "json" else "txt"
        report_path = output_dir / f"fulltest_{timestamp}.{report_ext}"
        report_path.write_text(report_text)
        logger.info("Report saved", path=str(report_path))

        # Always save JSON sidecar for programmatic comparison
        if self._bt_config.report_format != "json":
            json_report = format_json_report(result)
            json_path = output_dir / f"fulltest_{timestamp}.json"
            json_path.write_text(json_report)
            logger.info("JSON sidecar saved", path=str(json_path))

        return result

    async def _ensure_data(self) -> None:
        """Download any missing historical data."""
        logger.info("Checking historical data...")
        await download_historical_alpaca(
            symbols=self._bt_config.symbols,
            start=self._bt_config.start,
            end=self._bt_config.end,
            interval=self._bt_config.interval,
            data_dir=self._bt_config.data_dir,
        )

    def _build_isolated_config(self) -> Config:
        """Build a config with isolated Redis/DB settings."""
        config = copy.deepcopy(self._base_config)

        # Redis isolation
        config.redis.db = self._bt_config.redis_db
        config.redis.stream_prefix = f"{self._bt_config.stream_prefix}:ticks"

        # Database isolation
        config.database.database = self._bt_config.backtest_db_name

        # Aggregator streams
        config.aggregator.source_stream = f"{self._bt_config.stream_prefix}:ticks:us"
        config.aggregator.consumer_group = f"{self._bt_config.consumer_group_prefix}aggregator"
        config.aggregator.bar_stream_prefix = f"{self._bt_config.stream_prefix}:bars"

        # Strategy streams
        config.strategies.bar_stream = f"{self._bt_config.stream_prefix}:bars:1m:us"
        config.strategies.consumer_group = f"{self._bt_config.consumer_group_prefix}strategies"
        config.strategies.control_channel = f"bt:axtrade:strategy:control"

        # Gateway control channel isolation
        config.gateway.control_channel = "bt:axtrade:gateway:control"

        # Discovery settings. The universe is pre-seeded with DAILY bars
        # (see _preseed_universe_bars): scanning 1m bars for ~1500 symbols
        # would mean seeding ~150M rows, and daily data is the conventional
        # granularity for universe screening anyway. Scans are bounded by
        # the sim clock so they can't see future bars.
        config.discovery.auto_subscribe = True
        config.discovery.enabled = True
        config.discovery.min_score = 40.0
        config.discovery.interval = "1d"
        config.discovery.bar_limit = 50

        # Enable all strategies with position sizing within risk limits.
        # Default 100 shares * $500+ stocks exceeds max_position_value ($50K).
        # Use a conservative share count that works for any S&P price level.
        max_pos_value = float(config.oms.risk.max_position_value)
        # Assume worst-case ~$1200/share (high-end S&P), stay well under limit
        safe_position_size = int(max_pos_value / 1200)  # ~41 shares
        # Per-strategy cap so signals self-limit instead of being rejected at
        # the OMS. discovery_momentum already defaults to 10 internally.
        per_strategy_max_positions = 10
        # These strategies were designed for the static gateway universe but
        # don't gate by symbol on their own, so they end up trading whatever
        # discovery pushes onto the bar stream. Inject `allowed_symbols` so
        # they stay within the gateway 5. discovery_momentum gates by score
        # and pairs is symbol-bound by config, so neither needs this.
        narrowed_types = {
            "multi_timeframe",
            "mean_reversion",
            "momentum",
            "buy_hold",
            "overnight_reversal",
        }
        gateway_symbol_list = list(self._bt_config.symbols)
        overrides = self._bt_config.strategy_overrides
        config.strategies.enabled = []
        if self._bt_config.enabled_strategies is not None:
            unknown = set(self._bt_config.enabled_strategies) - set(STRATEGY_TYPES)
            if unknown:
                raise ValueError(
                    f"Unknown strategy types: {sorted(unknown)}. "
                    f"Available: {sorted(STRATEGY_TYPES)}"
                )
            chosen = list(self._bt_config.enabled_strategies)
        else:
            # buy_hold is a calibration benchmark, opt-in only.
            # overnight_reversal stays opt-in until it passes its IS/OOS
            # graduation gate (phase 3 iteration 7) — don't let a candidate
            # contaminate default comparison runs mid-validation.
            chosen = [
                t
                for t in STRATEGY_TYPES
                if t not in {"buy_hold", "overnight_reversal"}
            ]
        for stype in chosen:
            strat_cfg: dict = {
                "position_size": safe_position_size,
                "max_positions": per_strategy_max_positions,
            }
            if stype in narrowed_types:
                strat_cfg["allowed_symbols"] = gateway_symbol_list
            strat_cfg.update(overrides.get(stype, {}))
            logger.info(
                "Strategy config built",
                strategy_type=stype,
                config=strat_cfg,
            )
            config.strategies.enabled.append(
                StrategyInstanceConfig(
                    type=stype,
                    id=f"{stype}-bt",
                    enabled=True,
                    config=strat_cfg,
                )
            )

        # Raise the global cap above the sum of per-strategy caps so the OMS
        # is no longer the bottleneck (live config stays at 20).
        config.oms.max_positions = 50

        # Force paper mode
        config.oms.paper_mode = True

        # Tell the PaperBroker how much cash we actually have so it rejects
        # buys that would overdraw. Without this, the broker accepts any
        # quantity of buys and the open-position book balloons (see audit C5);
        # strategies hit per-position caps in the first ~12 simulated days
        # and stop trading for the rest of the period.
        config.oms.initial_capital = Decimal(str(self._bt_config.initial_capital))

        # Set gateway symbols from backtest config
        config.gateway.symbols = [
            SymbolConfig(symbol=s, base_price=100.0)
            for s in self._bt_config.symbols
        ]

        return config

    async def _preseed_universe_bars(self, config: Config) -> None:
        """Pre-seed TimescaleDB with DAILY bars aggregated from the parquet files.

        This gives the discovery service data to scan against for the full
        S&P universe, not just the user-specified backtest symbols. Bars are
        seeded for the entire window (daily granularity keeps that tractable:
        ~250 rows/symbol/year vs ~100k at 1m), and each daily bar is stamped
        with the day's LAST minute-bar timestamp. Combined with discovery's
        sim-time-bounded queries, a day's bar only becomes visible after that
        day closes — no look-ahead. (The previous implementation seeded the
        final 50 minute-bars of the window, which discovery then saw from
        sim t=0: it was scoring the universe on end-of-period prices.)
        """
        data_dir = Path(self._bt_config.data_dir)
        manifest_path = data_dir / "manifest.json"

        if not manifest_path.exists():
            logger.warning("No manifest found, skipping universe pre-seed")
            return

        with open(manifest_path) as f:
            manifest = json.load(f)

        files = manifest.get("files", [])
        if not files:
            logger.info("No files in manifest, skipping pre-seed")
            return

        # Connect to the backtest DB
        db_pool = DatabasePool(config.database)
        await db_pool.connect()
        bar_repo = BarRepository(db_pool)

        start_dt = pd.Timestamp(self._bt_config.start)
        end_dt = pd.Timestamp(self._bt_config.end)

        total_files = len(files)
        print(f"Pre-seeding universe daily bars ({total_files} files)...", file=sys.stderr, flush=True)

        # Read and filter all parquet files in parallel using a thread pool
        loop = asyncio.get_event_loop()

        def _read_one(file_info: dict) -> tuple[str, str, list[tuple]]:
            """Read a parquet file, aggregate to daily, return rows."""
            symbol = file_info["symbol"]
            file_path = data_dir / file_info["filename"]

            if not file_path.exists():
                return symbol, "1d", []

            try:
                table = pq.read_table(
                    file_path,
                    filters=[
                        ("timestamp", ">=", start_dt),
                        ("timestamp", "<", end_dt),
                    ],
                )
                if table.num_rows == 0:
                    return symbol, "1d", []

                df = table.to_pandas()
                del table

                return symbol, "1d", daily_rows_from_minute_df(df, symbol)
            except Exception as e:
                logger.debug("Failed to pre-seed file", symbol=symbol, error=str(e))
                return symbol, "1d", []

        try:
            all_rows: list[tuple] = []
            files_processed = 0
            total_inserted = 0
            interval = "1d"
            batch_limit = 50_000  # insert in chunks to avoid huge transactions

            with ThreadPoolExecutor(max_workers=8) as executor:
                futures = [
                    loop.run_in_executor(executor, _read_one, fi)
                    for fi in files
                ]

                for coro in asyncio.as_completed(futures):
                    symbol, intv, rows = await coro
                    interval = intv
                    all_rows.extend(rows)
                    files_processed += 1

                    if total_files > 0:
                        pct = files_processed * 100 // total_files
                        print(
                            f"\rPre-seed: {pct:3d}% ({files_processed}/{total_files} files, {len(all_rows)} rows)  ",
                            end="", file=sys.stderr, flush=True,
                        )

                    # Flush in batches to bound memory
                    if len(all_rows) >= batch_limit:
                        total_inserted += await bar_repo.bulk_insert_bars(all_rows, interval)
                        all_rows.clear()

            # Insert remaining rows
            if all_rows:
                total_inserted += await bar_repo.bulk_insert_bars(all_rows, interval)

            print(
                f"\rPre-seed: 100% ({files_processed}/{total_files} files, {total_inserted} rows) -- done.                    ",
                file=sys.stderr,
            )
            logger.info(
                "Universe pre-seed complete",
                files_processed=files_processed,
                total_rows_inserted=total_inserted,
            )
        finally:
            await db_pool.disconnect()

    async def _run_services(self, config: Config) -> FullBacktestResult:
        """Create and run all services, wait for completion."""
        result = FullBacktestResult(
            config=self._bt_config,
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc),
        )

        # Pace the replay producer to the aggregator: cap the tick-stream
        # backlog so the producer's position stays close to the consumer's
        # sim clock. Without this the producer finishes the whole window in
        # seconds, and discovery-driven add_symbols() (which fires on sim
        # time) arrives after the producer has exited — fed symbols never
        # replay. 20k ticks ≈ 5k bars ≈ ~12s of aggregator work.
        pace_client = aioredis.Redis(
            host=config.redis.host,
            port=config.redis.port,
            db=config.redis.db,
            decode_responses=True,
        )
        tick_stream = config.aggregator.source_stream
        agg_group = config.aggregator.consumer_group
        max_lag = 20_000

        async def _pace_producer() -> None:
            while True:
                lag = await _consumer_lag(pace_client, tick_stream, agg_group)
                if lag is None or lag <= max_lag:
                    return
                await asyncio.sleep(0.2)

        # Create replay adapter
        replay = ReplayAdapter(
            data_dir=self._bt_config.data_dir,
            ticks_per_bar=self._bt_config.ticks_per_bar,
            start_date=self._bt_config.start,
            end_date=self._bt_config.end,
            throttle=_pace_producer,
        )

        # Create services with isolated config
        gateway = GatewayService(config, adapter=replay)

        # Set up discovery and gateway control before strategy runner
        discovery_runner: Optional[BacktestDiscoveryRunner] = None
        discovery_service: Optional[DiscoveryService] = None
        gateway_control: Optional[GatewayControlPublisher] = None
        db_pool: Optional[DatabasePool] = None

        if self._bt_config.discovery_enabled:
            db_pool = DatabasePool(config.database)
            await db_pool.connect()

            discovery_service = DiscoveryService(db_pool=db_pool)
            await discovery_service.connect()

            # Create gateway control publisher for feeding discovered symbols
            gateway_control = GatewayControlPublisher(config.redis, config.gateway)
            await gateway_control.connect()

            symbol_provider = SP500SymbolProvider()
            discovery_runner = BacktestDiscoveryRunner(
                config=config,
                discovery_service=discovery_service,
                symbol_provider=symbol_provider,
                gateway_control=gateway_control,
            )

        # Create strategy runner with discovery service injected
        strategy_runner = StrategyRunner(config, discovery_service=discovery_service)

        # Create aggregator with discovery callback wired in
        aggregator = AggregatorService(
            config,
            on_bar_callback=discovery_runner.on_bar if discovery_runner else None,
        )

        # Run gateway, aggregator, and strategy runner concurrently
        gateway_task = asyncio.create_task(gateway.start())
        aggregator_task = asyncio.create_task(aggregator.start())
        strategy_task = asyncio.create_task(strategy_runner.start())

        logger.info("All services started, waiting for replay completion...")

        # Wait for replay to finish
        await replay.completion_event.wait()
        logger.info("Replay complete, draining pipeline...")

        # The replay producer finishes far ahead of the consumers. A fixed
        # grace period here used to truncate the simulation tail — the
        # 2025-08 calibration run kept only the first 7 trading days of
        # bars (28%) before the aggregator was stopped. Wait until each
        # consumer group has actually consumed its backlog instead.
        try:
            await _drain_stream(
                pace_client,
                config.aggregator.source_stream,
                config.aggregator.consumer_group,
                label="ticks->aggregator",
            )
            await aggregator.stop()
            logger.info("Aggregator stopped")

            await _drain_stream(
                pace_client,
                config.strategies.bar_stream,
                config.strategies.consumer_group,
                label="bars->strategies",
            )
            await strategy_runner.stop()
            logger.info("Strategy runner stopped")
        finally:
            await pace_client.aclose()

        # Stop gateway
        await gateway.stop()
        logger.info("Gateway stopped")

        # Cancel any remaining tasks
        for task in [gateway_task, aggregator_task, strategy_task]:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Clean up discovery and gateway control
        if discovery_runner and self._bt_config.discovery_enabled:
            result.discovery.total_scans = discovery_runner.scan_count
            result.discovery.symbols_discovered = discovery_runner.total_matches
            result.discovery.symbols_fed_to_gateway = len(discovery_runner.symbols_fed)
            result.discovery.symbols_fed_list = discovery_runner.symbols_fed

        if gateway_control:
            await gateway_control.disconnect()

        if db_pool:
            await db_pool.disconnect()

        # Populate basic stats
        result.total_bars_processed = replay.total_bars
        result.total_ticks_generated = replay.total_ticks

        return result
