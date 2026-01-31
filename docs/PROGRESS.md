# axtrade Development Progress

## Completed Iterations

### Iteration 1: Gateway and Tick Streaming (Complete)
- Mock and IBKR data adapters
- Redis Streams for tick publishing
- Gateway service with configurable symbols

### Iteration 2: Data Persistence (Complete)
- TimescaleDB integration for bar storage
- Indicator calculation (SMA-20, RSI-14)
- IndicatorEngine with rolling buffers
- CLI for querying historical bars
- `python -m axtrade.cli bars AAPL --limit 10`

### Iteration 3: First Strategy (Complete)
- OMS types: Order, Fill, Position with enums
- Database schema for positions, orders, fills
- BaseStrategy ABC with `on_bar()` interface
- MomentumBreakout strategy (RSI oversold entry, overbought/stop-loss exit)
- OrderManager with paper trading simulation
- StrategyRunner service consuming bars from Redis
- `make run-strategy`

### Iteration 4: Backtesting Framework (Complete)
- BacktestConfig, TradeRecord, EquityPoint, BacktestResult types
- SimulatedBroker for order execution simulation
- PerformanceAnalyzer with metrics:
  - Sharpe ratio, max drawdown, profit factor
  - Win rate, total return, annualized return
- BacktestEngine replaying historical bars through strategies
- CLI command: `python -m axtrade.cli backtest momentum --symbol AAPL --start 2024-01-01 --end 2024-01-31`

### Iteration 5: Live Trading Integration (Complete)
- BrokerProtocol abstract base class
- PaperBroker with slippage simulation
- IBKRBroker for live execution via ib_insync
- RiskManager with pre-trade checks:
  - Max position size/value limits
  - Max order size limit
  - Daily loss limit
  - Max open orders limit
- OrderManager refactored to use BrokerProtocol
- OrderRejectedError for risk violations
- Configuration: `oms.paper_mode: false` for live trading

### Iteration 6: Web Dashboard (Complete)
- FastAPI backend with REST API
- WebSocket for real-time position and P&L updates
- REST endpoints:
  - `GET /api/positions` - Open positions with P&L
  - `GET /api/orders` - Recent orders with filters
  - `GET /api/fills` - Fill history
  - `GET /api/pnl/summary` - Daily and cumulative P&L
  - `GET /ws` - WebSocket for live updates
- React frontend (Vite + TypeScript + Tailwind) at `src/axtrade/web/ui/`:
  - Overview: P&L cards, P&L chart, positions, alerts panel
  - Monitor: Orders table, Fills table, live WebSocket feed
  - Strategies: Strategy cards with status and P&L
  - Components: OrdersTable, FillsTable, AlertsPanel, PnLChart, AlertBadge
  - Custom hooks: useOrders, useFills, useAlerts, useHealth, usePnLHistory
- `make run-api` to start backend at http://localhost:8000
- `npm run dev` (in web/ui) to start frontend at http://localhost:5173

### Iteration 7: Additional Strategies (Complete)
- Bollinger Bands indicator (middle, upper, lower bands, %B, bandwidth)
- MeanReversionStrategy: Buy at lower band + RSI oversold, sell at upper band
- MultiTimeframeStrategy: 5m trend + 1m entry timing with take-profit/stop-loss
- PairsStrategy: Z-score based pairs trading on correlated symbols
- Strategies registered in STRATEGY_TYPES for dynamic loading
- Example configs in default.yaml (commented out)

### Iteration 8: Advanced Risk Management (Complete)
- ATR indicator for volatility measurement (simple and Wilder's smoothing)
- PositionSizer with multiple sizing methods:
  - Fixed size with max position limit
  - Risk percentage (% of equity at risk)
  - Kelly criterion with fractional Kelly
  - ATR-based volatility sizing
- PortfolioRisk for portfolio-level risk tracking:
  - Position/sector exposure tracking
  - Portfolio heat (total risk / equity)
  - Limit checks for new positions
  - Available risk capacity calculation
- SizingResult and PortfolioMetrics dataclasses

**New Files**:
- `src/axtrade/indicators/atr.py`
- `src/axtrade/oms/position_sizer.py`
- `src/axtrade/oms/portfolio_risk.py`

### Iteration 9: System Health Monitoring (Complete)
- Extensible alert system with channel architecture:
  - AlertChannel ABC for custom integrations (email, SMS, Slack ready)
  - LogChannel for logs + in-memory storage
  - CallbackChannel for testing and custom callbacks
- AlertService with deduplication and rate limiting
- AlertRepository with in-memory storage and rotation
- HealthMonitor for infrastructure checks:
  - Redis, Database, Broker connectivity checks
  - Heartbeat tracking for services
  - Latency monitoring with warning thresholds
  - Automatic alerts on status changes
- REST API endpoints:
  - `GET /api/alerts` - Recent alerts with filtering
  - `GET /api/alerts/counts` - Alert counts by severity
  - `POST /api/alerts/{id}/acknowledge` - Acknowledge alert
  - `GET /api/health/detailed` - System health status
- WebSocket broadcast for real-time alert notifications
- Frontend updates:
  - Alerts panel with severity indicators
  - Health status dots in header (R/D/B for Redis/Database/Broker)
  - Click-to-acknowledge alerts
  - Collapsible alerts section

**New Files**:
- `src/axtrade/alerts/` module (types.py, repository.py, channels.py, service.py, health.py)
- `src/axtrade/api/routes/alerts.py`
- `src/axtrade/api/routes/health.py`

### Iteration 10: Data Source Adapters (Complete)
- Alpaca adapter for market data
- Yahoo Finance adapter for historical data
- Additional gateway adapter implementations

### Iteration 11: Performance Analytics (Complete)
- Rolling performance metrics (Sharpe ratio, Sortino ratio, volatility)
- Drawdown analysis with DrawdownTracker
- Trade statistics (win rate, profit factor, expectancy)
- Strategy-level analytics and correlation matrix
- REST API endpoints for analytics data
- Frontend analytics cards display

**New Files**:
- `src/axtrade/analytics/` module (metrics.py, drawdown.py, trades.py, strategy.py)
- `src/axtrade/api/routes/analytics.py`

### Recent Additions
- `LoopSupervisor` for resilient service loops with exponential backoff (`common/resilience.py`)
- Parallel strategy execution in StrategyRunner consume loop (`strategies/runner.py`)
- React frontend with Vite + TypeScript + Tailwind (`web/ui/`):
  - OrdersTable component with status badges
  - FillsTable component
  - AlertsPanel with acknowledge functionality
  - PnLChart using recharts
  - AlertBadge in header showing unacknowledged count
  - Custom hooks for API polling (useOrders, useFills, useAlerts, useHealth)

## Test Coverage

Total tests: 618

| Module | Tests |
|--------|-------|
| Aggregator | 8 |
| Alerts | 26 |
| Alpaca Adapter | 17 |
| Analytics | 35 |
| API | 15 |
| ATR Indicator | 12 |
| Backtest | 20 |
| Bollinger | 14 |
| Database | 5 |
| Health | 19 |
| Indicators | 18 |
| OMS Types | 13 |
| OMS Broker | 16 |
| Portfolio Risk | 25 |
| Position Sizer | 18 |
| Resilience | 10 |
| Risk | 17 |
| Strategies | 15 |
| Strategies Extended | 21 |
| Yahoo Adapter | 15 |
| Other | 279 |

## Current Architecture

```
Gateway -> Redis (ticks) -> Aggregator -> Redis (bars) + TimescaleDB
                                |                |
                          IndicatorEngine        v
                           (SMA, RSI, ATR,  StrategyRunner -> OrderManager -> PostgreSQL
                            Bollinger)           |              |              (positions,
                                           [Strategies]   RiskManager         orders, fills)
                                                          PositionSizer
                                                          PortfolioRisk
                                                               |
                                                        BrokerProtocol
                                                         /        \
                                                  PaperBroker  IBKRBroker

                              +------------------+
                              |  FastAPI + WS    | <- http://localhost:8000
                              +--------+---------+
                                       |
                    +------------------+------------------+
                    |                  |                  |
             PositionRepo         OrderRepo          AlertRepo
                                                          |
                                                    AlertService
                                                     /    |    \
                                              LogChannel  ...  (future)
                                                    |
                                             HealthMonitor

                              +------------------+
                              |   React UI       | <- http://localhost:5173
                              | (Vite+TS+Tailwind)|
                              +------------------+
                              | Overview | Monitor | Strategies |
                              | - P&L Chart       |
                              | - Orders Table    |
                              | - Fills Table     |
                              | - Alerts Panel    |
                              +------------------+
```

## Potential Next Iterations

### Iteration 12: External Alert Channels
**Goal**: Add email, SMS, and Slack notification channels

**Key Components**:
- EmailChannel (SendGrid/SMTP)
- SMSChannel (Twilio)
- SlackChannel (Webhook)
- Channel configuration in YAML
- Alert routing rules

---

## Completed Plan Documents

Detailed implementation plans for completed iterations:
- `docs/iterations/iteration-3-plan.md` - First Strategy
- `docs/iterations/iteration-4-plan.md` - Backtesting Framework
- `docs/iterations/iteration-5-plan.md` - Live Trading Integration
- `docs/iterations/iteration-6-plan.md` - Web Dashboard
- `docs/iterations/iteration-7-plan.md` - Additional Strategies
- `docs/iterations/iteration-8-plan.md` - Advanced Risk Management
- `docs/iterations/iteration-9-plan.md` - System Health Monitoring
- `docs/iterations/iteration-11-plan.md` - Performance Analytics
