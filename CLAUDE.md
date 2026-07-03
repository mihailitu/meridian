# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

axtrade is a Python-based algorithmic trading platform supporting real-time market data ingestion, technical indicator calculation, and multi-strategy execution. Supports multiple data sources (Mock, IBKR, Alpaca, Yahoo) and paper/live trading modes.

Note: the repository directory is `meridian/`, but the Python package is `axtrade`. All `python -m axtrade.*` invocations refer to `src/axtrade/`.

## Build and Development Commands

```bash
# Setup
make dev                    # Create venv and install with dev dependencies
make install                # Create venv and install production only

# Infrastructure (docker-compose: Redis on port 6380, TimescaleDB on port 5433)
make infra                  # Start Redis + TimescaleDB
make infra-stop             # Stop all infrastructure

# Run Services
make run                    # Run gateway with mock adapter
make run-ibkr               # Run gateway with IBKR adapter
make run-alpaca             # Run gateway with Alpaca adapter
make run-yahoo              # Run gateway with Yahoo adapter
make run-aggregator         # Run bar aggregator service
make run-strategy           # Run strategy runner service
make run-api                # Run web dashboard API server
make build-ui               # Build frontend static bundle (served by api)

# Fulltest (historical replay through the full pipeline)
make run-fulltest-download ARGS="--start 2025-08-01 --end 2026-02-01 --symbols AAPL MSFT GOOGL"
make run-fulltest          ARGS="--start 2025-08-01 --end 2026-02-01 --symbols AAPL MSFT GOOGL --capital 100000"

# Frontend Development (from src/axtrade/web/ui/)
npm install                 # Install dependencies (first time)
npm run dev                 # Start Vite dev server at http://localhost:5173
npm run build               # Build for production

# Testing
make test                   # Run all tests
.venv/bin/pytest tests/unit/test_indicators.py -v           # Single test file
.venv/bin/pytest tests/unit/test_indicators.py::TestCalculateSMA -v  # Single test class
.venv/bin/pytest -k "test_rsi" -v                           # Tests matching pattern

# CLI (note: subcommands are required)
python -m axtrade.cli bars AAPL --limit 10 --interval 1m
python -m axtrade.cli backtest --strategy momentum --symbol AAPL --start 2024-01-01 --end 2024-01-31
python -m axtrade.fulltest download --start 2025-08-01 --end 2026-02-01 --symbols AAPL MSFT GOOGL
python -m axtrade.fulltest run      --start 2025-08-01 --end 2026-02-01 --symbols AAPL MSFT GOOGL --capital 100000

# Fulltest extras: --universe sp500|sp1500 instead of --symbols; --download on `run` auto-fetches missing data
# --strategies TYPE [TYPE ...] selects strategy types; default runs all EXCEPT ml_prediction,
# buy_hold, and overnight_reversal (opt-in: calibration benchmark / not yet through the IS/OOS gate)
# IS/OOS comparison: two back-to-back fulltests + side-by-side per-strategy report (PnL/PF/WR/Sharpe/verdict)
python -m axtrade.fulltest oos --is-start 2024-08-01 --is-end 2025-08-01 \
    --oos-start 2025-08-01 --oos-end 2026-02-01 \
    --symbols AAPL MSFT GOOGL AMZN NVDA --capital 100000 \
    --strategy-overrides params.yaml   # optional YAML {strategy_type: {param: value}}
```

Historical parquet data lives in `data/historical/` (~6.3 GB, S&P 1500 coverage for 2024-08→2025-08 and 2025-08→2026-02); fulltest reports go to `data/fulltest_results/`. Both are untracked (not in `.gitignore`) — never `git add` them.

## Architecture

Event-driven architecture with Redis Streams as the message bus:

```
Gateway -> Redis (ticks) -> Aggregator -> Redis (bars) + TimescaleDB
                                |                |
                          IndicatorEngine        v
                                           StrategyRunner -> OrderManager -> PostgreSQL
                                                |                             (positions,
                                           [Strategies]                        orders, fills)
```

### Core Data Flow

1. **Gateway** (`gateway/service.py`): Connects to data sources via `DataAdapter` (`gateway/base.py`), publishes ticks to `stream:ticks:us`. Supports dynamic symbol add/remove via Redis pubsub channel `axtrade:gateway:control` (`gateway/control.py`)
2. **Aggregator** (`aggregator/service.py`): Consumes ticks, builds OHLCV bars via `BarEngine`, calculates indicators via `IndicatorEngine`, persists to TimescaleDB, publishes to `stream:bars:{interval}:us`
3. **StrategyRunner** (`strategies/runner.py`): Consumes bars with indicators, executes enabled strategies in parallel, submits orders via `OrderManager`. Supports runtime enable/disable via Redis pubsub channel `axtrade:strategy:control`. Optionally injects `DiscoveryService` into strategies that support it
4. **OrderManager** (`oms/manager.py`): Manages order lifecycle via `BrokerProtocol` (`oms/broker.py`), pre-trade risk checks via `RiskManager`, position tracking, global max positions guard

### Redis Streams and Consumer Groups

- Tick stream: `stream:ticks:{market}` (e.g., `stream:ticks:us`)
- Bar streams: `stream:bars:{interval}:{market}` (e.g., `stream:bars:1m:us`)
- Fill stream: `stream:fills`
- Consumer groups: `aggregator` (ticks), `strategies` (bars)
- Pubsub control: `axtrade:strategy:control`

### Service Entry Points

Each service is runnable as a Python module:
- `python -m axtrade.gateway --adapter mock|ibkr|alpaca|yahoo`
- `python -m axtrade.aggregator`
- `python -m axtrade.strategies`
- `python -m axtrade.api.app` (FastAPI on port 8000, serves frontend static build and provides REST + WebSocket)

### Key Extension Points

**Adding a data adapter**: Implement `DataAdapter` ABC in `gateway/base.py` (`connect`, `disconnect`, `subscribe`, `stream_ticks`). Register in gateway service.

**Adding a strategy**: Inherit from `BaseStrategy` in `strategies/base.py`, implement `on_bar(data: BarWithIndicators) -> Optional[Order]`. Register the strategy name in `strategies/__init__.py` and add to `strategies.enabled` list in `config/default.yaml`. Non-discovery strategies should honor the `allowed_symbols` config key (universe filter) — when discovery `auto_subscribe` is on, the bar stream carries 50+ discovered symbols, and strategies without the filter will trade all of them. The fulltest orchestrator injects `allowed_symbols` (the gateway symbol list) into `momentum`, `mean_reversion`, `multi_timeframe`, `buy_hold`, and `overnight_reversal` (see `narrowed_types` in `fulltest/orchestrator.py` — add new non-discovery strategies there too).

**Adding a broker**: Implement `BrokerProtocol` in `oms/broker.py` (`submit_order`, `cancel_order`, `get_positions`, `set_fill_callback`).

**Adding a symbol source**: Implement `SymbolProvider` protocol in `discovery/providers.py` (`async get_symbols() -> list[str]`). Pass it to `DiscoveryRunner` instead of `ConfigSymbolProvider`.

**Discovery-to-trading bridge**: Set `discovery.auto_subscribe: true` in config. `DiscoveryRunner` pushes high-score symbols to gateway via `GatewayControlPublisher` (Redis pubsub). Gateway dynamically subscribes via `DataAdapter.add_symbols()`. The `discovery_momentum` strategy trades discovered symbols using scores from `DiscoveryService`.

### Key Modules

- `common/`: Shared types (`Tick`, `Bar` as frozen dataclasses), config loading (`load_config()` from `config/default.yaml`), Redis messaging (`RedisPublisher`, `RedisConsumer`, `BarPublisher`, `BarConsumer`), database (`DatabasePool`, `BarRepository`), `LoopSupervisor` for resilient service loops with exponential backoff
- `gateway/`: Data adapters implementing `DataAdapter` - Mock, IBKR (`ib_insync`), Alpaca, Yahoo
- `indicators/`: `IndicatorEngine` with rolling buffers for SMA, RSI, Bollinger Bands, ATR, and market regime detection
- `strategies/`: `BaseStrategy` ABC with implementations: `momentum`, `mean_reversion`, `multi_timeframe`, `pairs`, `ml_prediction`, `discovery_momentum`, `overnight_reversal`, and `buy_hold` (a calibration benchmark whose fulltest result is computable by hand — used to validate the harness's fill/accounting/reporting paths, not to trade)
- `oms/`: `OrderManager`, `BrokerProtocol` (PaperBroker/IBKRBroker), `RiskManager`, `PositionSizer` (fixed/risk-pct/Kelly/ATR-based), `PortfolioRisk` tracking
- `backtest/`: `BacktestEngine`, `SimulatedBroker`, `PerformanceAnalyzer`
- `fulltest/`: Full system backtest running the complete pipeline (gateway, aggregator, strategy runner, discovery) against historical data with isolated Redis DB and TimescaleDB. `ReplayAdapter` converts parquet OHLCV data to synthetic ticks. `FullBacktestOrchestrator` coordinates all services in-process. Downloads data via Alpaca API. `SP500SymbolProvider` / `SP1500SymbolProvider` in `fulltest/universe.py` for discovery universes. `comparison.py` backs the `oos` subcommand (IS vs OOS per-strategy report). Defaults to `--redis-db 1` and `--db-name axtrade_backtest` so it never touches live state (db=0 / `axtrade`)
- `api/`: FastAPI app with route modules in `api/routes/`. OpenAPI docs at `/docs`
- `web/ui/`: React frontend (Vite + TypeScript + Tailwind + Recharts)
- `alerts/`: Alert system with channels, deduplication, and health monitoring
- `analytics/`: Performance analytics (`metrics`, `drawdown`, `trades`, per-strategy aggregation) shared by backtest, fulltest, and the API
- `ml/`: ML model scaffolding (`features`, `inference`, `models`, `types`) backing the `ml_prediction` strategy
- `discovery/`: Symbol screening with momentum, volatility, volume, and trend screeners. `DiscoveryRunner` runs periodic background scans via `LoopSupervisor`, optionally feeds discovered symbols to gateway via `GatewayControlPublisher` when `auto_subscribe` is enabled. `SymbolProvider` protocol enables pluggable symbol sources (default: `ConfigSymbolProvider` reads from gateway config)

### Database

TimescaleDB (PostgreSQL) with schema initialized by `scripts/init-db.sql` (creates `bars` hypertable, `positions`, `orders`, `fills` tables). Migrations in `scripts/migrations/` cover strategy state, regime tracking, discovery, multi-market, and ML model tables.

### Configuration

Loaded from `config/default.yaml` via `load_config()`. Alpaca credentials come from `.env` file (loaded via `python-dotenv`). Key sections: `gateway` (adapter, symbols, control_channel), `redis` (host, port, db), `aggregator` (intervals, streams), `database`, `indicators`, `oms` (paper_mode, max_positions, risk limits), `strategies` (enabled list), `api`, `discovery` (enabled, scan_interval_seconds, bar_limit, interval, auto_subscribe, min_score, max_positions). Redis `db` field (default 0) enables database isolation for backtesting.

`discovery_momentum` is shipped with `enabled: false` in `config/default.yaml` — flip it on to exercise the discovery→trading bridge.

### Project Docs

`ROADMAP.md` is the canonical "where the project is / what's next" doc — read it before starting strategy or platform work, and keep it updated when a phase lands. Supporting detail lives in `docs/` (`active-plan.md` for the current phased plan, `PROGRESS.md` for history, `strategy-logic-fixes.md` and `AUDIT-2026-05-02.md` for findings, `phase3-trustworthy-harness.md` + `docs/iterations/` for the phase-3 harness-fix and strategy-iteration log).

### Helper Scripts

- `scripts/start-all.sh` / `stop-all.sh` - Start/stop all services
- `scripts/status.sh` - Check service status
- `scripts/reset-paper-trading.sh` - Reset paper trading state
- `scripts/collect_historical.py` - Collect historical data

## Code Conventions

- Python 3.11+, all services use asyncio
- Structured logging via `structlog` - use `get_logger()` from common
- Market data types are frozen dataclasses (`Tick`, `Bar`)
- OMS types use mutable dataclasses (`Order`, `Fill`, `Position`) with `Decimal` for monetary values
- Strategies inherit from `BaseStrategy` ABC and implement `on_bar()` method
- Tests use pytest-asyncio with `asyncio_mode = "auto"`, fixtures in `tests/conftest.py`
- Non-default ports: Redis on 6380, TimescaleDB on 5433
