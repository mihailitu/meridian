# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

axtrade is a Python-based algorithmic trading platform supporting real-time market data ingestion, technical indicator calculation, and multi-strategy execution. Supports multiple data sources (Mock, IBKR, Alpaca, Yahoo) and paper/live trading modes.

## Build and Development Commands

```bash
# Setup
make dev                    # Create venv and install with dev dependencies
make install                # Create venv and install production only

# Infrastructure
make infra                  # Start Redis + TimescaleDB
make infra-stop             # Stop all infrastructure
make redis                  # Start Redis only
make db                     # Start TimescaleDB only

# Run Services
make run                    # Run gateway with mock adapter
make run-ibkr               # Run gateway with IBKR adapter
make run-alpaca             # Run gateway with Alpaca adapter
make run-yahoo              # Run gateway with Yahoo adapter
make run-aggregator         # Run bar aggregator service
make run-strategy           # Run strategy runner service
make run-api                # Run web dashboard API server

# Frontend Development
cd src/axtrade/web/ui
npm install                 # Install dependencies (first time)
npm run dev                 # Start Vite dev server at http://localhost:5173
npm run build               # Build for production
npm run lint                # Run ESLint

# Testing
make test                   # Run all tests
.venv/bin/pytest tests/unit/test_indicators.py -v           # Single test file
.venv/bin/pytest tests/unit/test_indicators.py::TestCalculateSMA -v  # Single test class
.venv/bin/pytest -k "test_rsi" -v                           # Tests matching pattern

# CLI
python -m axtrade.cli bars AAPL --limit 10 --interval 1m   # Query historical bars
python -m axtrade.cli backtest momentum --symbol AAPL --start 2024-01-01 --end 2024-01-31  # Run backtest
```

## Architecture

The system uses an event-driven architecture with Redis Streams as the message bus:

```
Gateway -> Redis (ticks) -> Aggregator -> Redis (bars) + TimescaleDB
                                |                |
                          IndicatorEngine        v
                                           StrategyRunner -> OrderManager -> PostgreSQL
                                                |                             (positions,
                                           [Strategies]                        orders, fills)
```

### Core Data Flow

1. **Gateway** (`gateway/service.py`): Connects to data sources (Mock, IBKR, Alpaca, or Yahoo), publishes ticks to `stream:ticks:us`
2. **Aggregator** (`aggregator/service.py`): Consumes ticks, builds OHLCV bars via `BarEngine`, calculates indicators via `IndicatorEngine`, persists to TimescaleDB, publishes to `stream:bars:{interval}:us`
3. **StrategyRunner** (`strategies/runner.py`): Consumes bars with indicators, executes enabled strategies in parallel, submits orders via `OrderManager`
4. **OrderManager** (`oms/manager.py`): Manages order lifecycle via `BrokerProtocol` (paper or live IBKR), pre-trade risk checks via `RiskManager`, position tracking
5. **CLI** (`cli/`): Queries historical bars from TimescaleDB

### Key Modules

- `common/`: Shared types (`Tick`, `Bar`), config loading, Redis messaging (`RedisPublisher`, `RedisConsumer`, `BarPublisher`, `BarConsumer`), database (`DatabasePool`, `BarRepository`), `LoopSupervisor` for resilient service loops with exponential backoff
- `gateway/`: Data adapters implementing `DataAdapter` base class - `MockAdapter` (testing), `IBKRAdapter` (live via `ib_insync`), `AlpacaAdapter`, `YahooAdapter`
- `aggregator/`: `BarEngine` for tick-to-bar aggregation, service orchestration
- `indicators/`: `IndicatorEngine` with rolling buffers, `calculate_sma`, `calculate_rsi`, `calculate_bollinger_bands`, `calculate_atr`, market regime detection
- `strategies/`: `BaseStrategy` ABC, strategy implementations (`MomentumBreakout`, `MeanReversionStrategy`, `MultiTimeframeStrategy`, `PairsStrategy`, `MLPredictionStrategy`), `StrategyRunner` service with dynamic control via Redis pubsub
- `oms/`: Order Management System - `Order`, `Fill`, `Position` types, `OrderManager`, `BrokerProtocol` with `PaperBroker`/`IBKRBroker`, `RiskManager` for pre-trade checks, `PositionSizer` (fixed/risk-pct/Kelly/ATR-based), `PortfolioRisk` tracking, `OrderRepository`, `PositionRepository`
- `backtest/`: Backtesting framework - `BacktestEngine`, `SimulatedBroker`, `PerformanceAnalyzer` for strategy evaluation on historical data
- `api/`: Web dashboard - FastAPI app with REST endpoints and WebSocket for real-time updates
- `web/ui/`: React frontend (Vite + TypeScript + Tailwind) with components for positions, orders, fills, alerts, and P&L chart
- `alerts/`: Alert system with channels, deduplication, and health monitoring
- `analytics/`: Performance analytics - rolling metrics, drawdown tracking, trade statistics
- `discovery/`: Symbol screening service with momentum, volatility, volume, and trend screeners
- `ml/`: ML prediction strategy with feature engineering and model inference

### API Endpoints

The web dashboard runs at `http://localhost:8000`:
- `GET /api/positions` - Open positions with P&L
- `GET /api/orders` - Recent orders with status filters
- `GET /api/fills` - Fill history
- `GET /api/pnl/summary` - Daily and cumulative P&L
- `GET /api/alerts` - Recent alerts with filtering
- `GET /api/alerts/counts` - Alert counts by severity
- `POST /api/alerts/{id}/acknowledge` - Acknowledge alert
- `GET /api/health/detailed` - System health status
- `GET /api/analytics/metrics` - Performance metrics (Sharpe, Sortino, drawdown)
- `GET /api/analytics/strategies` - Strategy-level analytics
- `GET /api/strategies` - Strategy status and controls
- `GET /api/regime` - Current market regime (trend + volatility state)
- `GET /api/discovery/results` - Symbol screening results
- `GET /api/markets` - Multi-market data (us, eu, asia, crypto, forex)
- `GET /api/ml/predictions` - ML model predictions
- `GET /ws` - WebSocket for real-time position/P&L updates
- `GET /health` - Health check
- `GET /docs` - OpenAPI documentation

### Configuration

Configuration is loaded from `config/default.yaml` via `load_config()`. Key sections:
- `gateway.adapter`: "mock", "ibkr", "alpaca", or "yahoo"
- `gateway.symbols`: List of symbols with base prices
- `aggregator.intervals`: Bar intervals to aggregate (e.g., "1m", "5m")
- `database`: TimescaleDB connection settings
- `indicators`: SMA/RSI periods, regime detection parameters
- `oms`: Order management settings - `paper_mode`, `slippage_bps`, `risk` (position/order limits, daily loss limit)
- `strategies`: Strategy runner config - `bar_stream`, `consumer_group`, `enabled` list with strategy instances
- `api`: Web API config - `host`, `port`, `cors_origins`
- `discovery`: Symbol screening config - `scan_interval_seconds`, `screeners` list

## Code Conventions

- All services use Python asyncio
- Structured logging via `structlog` - use `get_logger()` from common
- Market data types are frozen dataclasses (`Tick`, `Bar`)
- OMS types use mutable dataclasses (`Order`, `Fill`, `Position`) with `Decimal` for monetary values
- Strategies inherit from `BaseStrategy` ABC and implement `on_bar()` method
- Tests use pytest-asyncio with `asyncio_mode = "auto"`
