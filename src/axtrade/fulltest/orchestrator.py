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

import re

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
from axtrade.gateway.control import GatewayControlPublisher
from axtrade.gateway.service import GatewayService
from axtrade.indicators.engine import IndicatorEngine
from axtrade.oms import OrderManager
from axtrade.strategies import STRATEGY_TYPES
from axtrade.strategies.base import BarWithIndicators, BaseStrategy
from axtrade.strategies.runner import StrategyRunner

from .data import download_historical_alpaca
from .discovery import BacktestDiscoveryRunner
from .isolation import BacktestInfrastructure
from .replay_adapter import ReplayAdapter
from .report import ReportGenerator, format_json_report, format_text_report
from .types import FullBacktestConfig, FullBacktestResult
from .universe import SP1500SymbolProvider

logger = get_logger("fulltest.orchestrator")


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

        # Discovery settings
        config.discovery.auto_subscribe = True
        config.discovery.enabled = True
        config.discovery.min_score = 40.0

        # Enable all strategies with position sizing within risk limits.
        # Default 100 shares * $500+ stocks exceeds max_position_value ($50K).
        # Use a conservative share count that works for any S&P price level.
        max_pos_value = float(config.oms.risk.max_position_value)
        # Assume worst-case ~$1200/share (high-end S&P), stay well under limit
        safe_position_size = int(max_pos_value / 1200)  # ~41 shares
        config.strategies.enabled = []
        skip_strategies = {"ml_prediction"}
        for stype, sclass in STRATEGY_TYPES.items():
            if stype in skip_strategies:
                continue
            config.strategies.enabled.append(
                StrategyInstanceConfig(
                    type=stype,
                    id=f"{stype}-bt",
                    enabled=True,
                    config={"position_size": safe_position_size},
                )
            )

        # Force paper mode
        config.oms.paper_mode = True

        # Set gateway symbols from backtest config
        config.gateway.symbols = [
            SymbolConfig(symbol=s, base_price=100.0)
            for s in self._bt_config.symbols
        ]

        return config

    async def _preseed_universe_bars(self, config: Config) -> None:
        """Pre-seed TimescaleDB with bars from all parquet files in the manifest.

        This gives the discovery service data to scan against for the full
        S&P universe, not just the user-specified backtest symbols.
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
        bar_limit = config.discovery.bar_limit  # only keep last N bars per symbol

        total_files = len(files)
        print(f"Pre-seeding universe bars ({total_files} files, tail {bar_limit}/symbol)...", file=sys.stderr, flush=True)

        # Read and filter all parquet files in parallel using a thread pool
        loop = asyncio.get_event_loop()

        def _read_one(file_info: dict) -> tuple[str, str, list[tuple]]:
            """Read a single parquet file with predicate pushdown, return rows."""
            symbol = file_info["symbol"]
            interval = file_info.get("interval", "1m")
            file_path = data_dir / file_info["filename"]

            if not file_path.exists():
                return symbol, interval, []

            try:
                table = pq.read_table(
                    file_path,
                    filters=[
                        ("timestamp", ">=", start_dt),
                        ("timestamp", "<", end_dt),
                    ],
                )
                if table.num_rows == 0:
                    return symbol, interval, []

                df = table.to_pandas()
                del table

                # Keep only the last N bars per symbol (discovery only needs recent history)
                df = df.tail(bar_limit)

                # Ensure timezone-aware timestamps
                ts_series = df["timestamp"]
                if ts_series.dt.tz is None:
                    ts_series = ts_series.dt.tz_localize("UTC")

                has_sma = "sma_20" in df.columns
                has_rsi = "rsi_14" in df.columns

                rows = []
                ts_vals = ts_series.to_list()
                open_vals = df["open"].to_list()
                high_vals = df["high"].to_list()
                low_vals = df["low"].to_list()
                close_vals = df["close"].to_list()
                vol_vals = df["volume"].to_list()
                sma_vals = df["sma_20"].to_list() if has_sma else [None] * len(ts_vals)
                rsi_vals = df["rsi_14"].to_list() if has_rsi else [None] * len(ts_vals)

                for i in range(len(ts_vals)):
                    sma_v = sma_vals[i]
                    rsi_v = rsi_vals[i]
                    rows.append((
                        ts_vals[i],
                        symbol,
                        Decimal(str(float(open_vals[i]))),
                        Decimal(str(float(high_vals[i]))),
                        Decimal(str(float(low_vals[i]))),
                        Decimal(str(float(close_vals[i]))),
                        int(vol_vals[i]),
                        Decimal(str(float(sma_v))) if sma_v is not None and not pd.isna(sma_v) else None,
                        Decimal(str(float(rsi_v))) if rsi_v is not None and not pd.isna(rsi_v) else None,
                    ))
                return symbol, interval, rows
            except Exception as e:
                logger.debug("Failed to pre-seed file", symbol=symbol, error=str(e))
                return symbol, interval, []

        try:
            all_rows: list[tuple] = []
            files_processed = 0
            total_inserted = 0
            interval = "1m"
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
        """Run the direct pipeline — no Redis, no tick generation."""
        return await self._run_direct(config)

    async def _run_direct(self, config: Config) -> FullBacktestResult:
        """Direct pipeline: parquet -> indicators -> strategies -> OrderManager.

        Replaces the 3-service Redis architecture with a single loop.
        """
        result = FullBacktestResult(
            config=self._bt_config,
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc),
        )

        # Create replay adapter (reuse for stream_bars())
        replay = ReplayAdapter(
            data_dir=self._bt_config.data_dir,
            ticks_per_bar=self._bt_config.ticks_per_bar,
            start_date=self._bt_config.start,
            end_date=self._bt_config.end,
        )
        await replay.connect()
        await replay.subscribe([
            SymbolConfig(symbol=s, base_price=100.0)
            for s in self._bt_config.symbols
        ])

        # Database for OrderManager and bar persistence
        db_pool = DatabasePool(config.database)
        await db_pool.connect()
        bar_repo = BarRepository(db_pool)

        # Indicator engine
        indicator_engine = IndicatorEngine(
            sma_period=config.indicators.sma_period,
            rsi_period=config.indicators.rsi_period,
        )

        # Order manager (uses DB for positions/orders/fills)
        order_manager = OrderManager(config, db_pool)
        await order_manager.connect()

        # Discovery setup
        discovery_runner: Optional[BacktestDiscoveryRunner] = None
        discovery_service: Optional[DiscoveryService] = None

        if self._bt_config.discovery_enabled:
            discovery_service = DiscoveryService(db_pool=db_pool)
            await discovery_service.connect()

            symbol_provider = SP1500SymbolProvider()
            discovery_runner = BacktestDiscoveryRunner(
                config=config,
                discovery_service=discovery_service,
                symbol_provider=symbol_provider,
                scan_interval_bars=self._bt_config.discovery_scan_interval_bars,
                add_symbols_callback=replay.add_symbols_sync,
            )

        # Load strategies
        strategies: list[BaseStrategy] = []
        skip_strategies = {"ml_prediction"}
        for strat_config in config.strategies.enabled:
            if not strat_config.enabled:
                continue
            strategy_class = STRATEGY_TYPES.get(strat_config.type)
            if not strategy_class:
                continue
            strategy = strategy_class(
                strategy_id=strat_config.id,
                config=strat_config.config,
            )
            # Inject discovery service if supported
            if discovery_service and hasattr(strategy, "set_discovery_service"):
                strategy.set_discovery_service(discovery_service)
            strategies.append(strategy)

        logger.info(
            "Direct pipeline ready",
            strategies=len(strategies),
            symbols=len(self._bt_config.symbols),
        )

        # Run one discovery scan up front using pre-seeded bar data.
        # The pre-seed already loaded recent bars for the full universe,
        # so scanning once discovers the same symbols that repeated scans
        # would find (the pre-seeded bars don't change during replay).
        if discovery_runner:
            discovery_runner._bar_count = self._bt_config.discovery_scan_interval_bars - 1
            await discovery_runner.on_bar()
            logger.info(
                "Initial discovery scan complete",
                symbols_fed=len(discovery_runner.symbols_fed),
            )

        # Main loop — pure computation, no DB writes except OrderManager
        bar_count = 0
        current_trading_date: Optional[str] = None
        logged_errors: set[str] = set()

        for bar in replay.stream_bars():
            bar_count += 1

            # Compute indicators
            indicators = indicator_engine.process_bar(
                symbol=bar.symbol,
                interval=bar.interval,
                close=bar.close,
                high=bar.high,
                low=bar.low,
            )

            data = BarWithIndicators(
                bar=bar,
                sma_20=indicators.sma_20,
                rsi_14=indicators.rsi_14,
                regime=indicators.regime,
                trend=indicators.trend,
                volatility=indicators.volatility,
                trend_strength=indicators.trend_strength,
                volatility_percentile=indicators.volatility_percentile,
            )

            # Update price cache + reset daily risk counters
            order_manager.update_price(bar.symbol, bar.close)

            bar_date = bar.timestamp.strftime("%Y-%m-%d")
            if bar_date != current_trading_date:
                if current_trading_date is not None:
                    rm = order_manager.risk_manager
                    if rm:
                        rm.reset_daily()
                        logged_errors.clear()
                        logger.info("New trading day, reset daily risk", date=bar_date)
                current_trading_date = bar_date

            # Run all strategies
            for strategy in strategies:
                if not strategy.enabled:
                    continue
                try:
                    order = strategy.on_bar(data)
                except Exception as e:
                    err_key = str(e)
                    if err_key not in logged_errors:
                        logged_errors.add(err_key)
                        logger.error("Strategy error: %s", err_key)
                    continue

                if not order:
                    continue

                try:
                    await order_manager.submit_order(order)
                    position = await order_manager.get_position(
                        strategy.strategy_id, order.symbol
                    )
                    if position:
                        strategy.update_position(position)
                    else:
                        strategy.clear_position(order.symbol)
                except Exception as e:
                    err_key = re.sub(r"\$[\d,.]+", "$X", f"{strategy.name}: {e}")
                    if err_key not in logged_errors:
                        logged_errors.add(err_key)
                        logger.warning("Order rejected: %s", err_key)

            # Yield to event loop periodically (for DB writes in OrderManager)
            if bar_count % 1000 == 0:
                await asyncio.sleep(0)

        # Populate discovery stats
        if discovery_runner and self._bt_config.discovery_enabled:
            result.discovery.total_scans = discovery_runner.scan_count
            result.discovery.symbols_discovered = discovery_runner.total_matches
            result.discovery.symbols_fed_to_gateway = len(discovery_runner.symbols_fed)
            result.discovery.symbols_fed_list = discovery_runner.symbols_fed

        # Clean up
        await order_manager.disconnect()
        await db_pool.disconnect()

        result.total_bars_processed = replay.total_bars
        result.total_ticks_generated = 0

        logger.info(
            "Direct pipeline complete",
            bars=bar_count,
            strategies=len(strategies),
        )

        return result
