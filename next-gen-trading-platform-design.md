# Next-Generation Global Trading Platform

## Design Document v2.0

> **Status (2026-07-03, supersedes 2026-05-04 note):** Historical document — the original
> January 2026 vision. Useful for component-level design context only. The following
> ambitions are **retired, not deferred** (phase-4 platform pivot,
> [`docs/phase4-platform-pivot.md`](docs/phase4-platform-pivot.md)): multi-market coverage
> (§2), millisecond-level execution latency, horizontal scaling / clone-and-distribute,
> the ML/AI strategy layer, `on_tick`/`on_regime_change` strategy hooks, and dynamic
> capital allocation. Rationale: the strategy-search phase concluded 2026-06-13 with six
> honest failures (see [`ROADMAP.md`](ROADMAP.md) per-strategy table); there is no strategy
> to scale, and millisecond latency is irrelevant at any horizon this stack can compete at.
> The project's success criterion is now a trustworthy strategy-evaluation platform with
> live paper-trading capability. See [`docs/AUDIT-2026-05-02.md`](docs/AUDIT-2026-05-02.md)
> §B1–B5 for the build-vs-design deviations.

---

## 1. Executive Summary

A high-performance, globally distributed trading platform supporting:
- **2,000-10,000+ symbols** across global markets
- **Millisecond-level execution** latency
- **Multiple independent strategies** running concurrently
- **Real-time analytics** and ML/AI strategies
- **Horizontal scaling** via strategy distribution across machines

### Core Philosophy
- **Pure Python**: Entire backend in Python - sufficient for retail trading scale
- **Event-driven architecture**: All components communicate via Redis Streams
- **Strategy isolation**: Each strategy manages its own positions and P&L independently
- **Clone-and-distribute**: Same codebase runs on multiple machines, each handling different strategies
- **Iterative delivery**: Working system in weeks, not months

### Current Scope (v1)
- **Equities only** (options and crypto deferred)
- **IBKR as sole broker** (no account yet - setup required)
- **ML with local GPU training** (NVIDIA)
- **Dynamic capital allocation** (performance-based)
- **Email + Dashboard notifications**
- **Single 32GB/20-core primary server**, distributable to additional machines

---

## 2. Global Market Coverage

### Phased Market Rollout

Markets are enabled incrementally to validate architecture before adding complexity.

#### Phase A: US Markets (Iteration 1-2)
| Region | Exchange | Trading Hours (Local) | UTC | Symbols | IBKR Data Cost |
|--------|----------|----------------------|-----|---------|----------------|
| **US** | NYSE, NASDAQ, AMEX | 09:30-16:00 ET | 14:30-21:00 | ~8,000 | ~$15/mo |

#### Phase B: Europe (Iteration 3)
| Region | Exchange | Trading Hours (Local) | UTC | Symbols | IBKR Data Cost |
|--------|----------|----------------------|-----|---------|----------------|
| **UK** | LSE | 08:00-16:30 GMT | 08:00-16:30 | ~2,000 | ~$6/mo |
| **Germany** | XETRA | 09:00-17:30 CET | 08:00-16:30 | ~1,500 | ~$5/mo |

#### Phase C: Asia (Iteration 4)
| Region | Exchange | Trading Hours (Local) | UTC | Symbols | IBKR Data Cost |
|--------|----------|----------------------|-----|---------|----------------|
| **Japan** | TSE | 09:00-15:00 JST | 00:00-06:00 | ~3,800 | ~$3/mo |
| **Hong Kong** | HKEX | 09:30-16:00 HKT | 01:30-08:00 | ~2,600 | ~$45/mo |

#### Future Phases (Deferred)
| Region | Exchange | Notes | Status |
|--------|----------|-------|--------|
| **Canada** | TSX, TSX-V | Similar hours to US | Deferred |
| **Crypto** | Binance, Coinbase | 24/7 | Deferred |
| **Options** | CBOE, etc. | Complex Greeks management | Deferred |
| **France** | Euronext Paris | Via IBKR | Deferred |
| **Australia** | ASX | Via IBKR | Deferred |

### Market Hours Visualization (UTC)

```
Hour:  00 01 02 03 04 05 06 07 08 09 10 11 12 13 14 15 16 17 18 19 20 21 22 23
       |--|--|--|--|--|--|--|--|--|--|--|--|--|--|--|--|--|--|--|--|--|--|--|--|
Japan  [========]
HK        [===========]
Europe                      [=================]
UK                          [==================]
US                                            [==============]
Crypto [================================================]
```

**Coverage**: Near 24-hour equity trading with strategic overlap periods.

---

## 3. Data Provider Strategy

### Primary: Interactive Brokers (IBKR)

**Account Setup Required:**
- Open IBKR Pro account (not Lite - need full API access)
- Minimum deposit varies by region (~$0-2000 for cash account)
- Enable API access in Account Management
- Download TWS or IB Gateway

**Pros:**
- Single API for global markets (150+ markets)
- Real-time streaming data
- Direct order execution
- Reasonable data costs (~$30-75/month for our markets)

**Cons:**
- Rate limits on market data (100 simultaneous subscriptions for streaming)
- API complexity (mitigated by ib_insync Python library)
- TWS/Gateway must run alongside our system

**Solution for rate limits:**
- Use snapshot requests for non-priority symbols
- Rotate streaming subscriptions based on active strategies
- Supplement with Polygon.io for unlimited US symbols

### Secondary Providers (Fallback/Supplement)

| Provider | Use Case | Cost | Latency |
|----------|----------|------|---------|
| **Polygon.io** | US equities, unlimited symbols | $200/mo | <100ms |
| **IEX Cloud** | US data, good free tier | $0-500/mo | <1s |
| **Alpha Vantage** | Development, backtesting | Free-$50/mo | Delayed |
| **Yahoo Finance** | EOD data, backup | Free | Delayed |
| **CoinGecko/Binance** | Crypto data | Free/Low | Real-time |
| **Quandl/Nasdaq** | Fundamentals, alternative data | Varies | EOD |

### Recommended Data Architecture

```
                    +------------------+
                    |  Data Gateway    |
                    |  (Python/asyncio)|
                    +--------+---------+
                             |
        +--------------------+--------------------+
        |                    |                    |
+-------v-------+    +-------v-------+    +-------v-------+
| IBKR Adapter  |    | Polygon       |    | (Future)      |
| (ib_insync)   |    | Adapter       |    |               |
+---------------+    +---------------+    +---------------+
```

---

## 4. System Architecture

### Design Principles

1. **Pure Python**: All components in Python - sufficient for retail trading
2. **Optimize in Python**: Use numpy, numba, multiprocessing if needed
3. **Clone-and-distribute**: Same codebase, different config per machine
4. **Shared state via Redis**: All machines connect to primary Redis/DB

### High-Level Component Diagram

```
+------------------------------------------------------------------+
|                      PRIMARY SERVER (32GB/20-core)                 |
|                                                                    |
|  +-------------------+  +-------------------+  +----------------+  |
|  | Market Data       |  | Redis             |  | TimescaleDB    |  |
|  | Gateway (Python)  |  | (Streams + Cache) |  | + PostgreSQL   |  |
|  | - IBKR via        |  |                   |  |                |  |
|  |   ib_insync       |  | Port 6379         |  | Port 5432      |  |
|  | - Polygon.io      |  +-------------------+  +----------------+  |
|  +-------------------+                                             |
|                                                                    |
|  +-------------------+  +-------------------+  +----------------+  |
|  | Strategy Runner   |  | Order Manager     |  | Dashboard      |  |
|  | - Momentum        |  | (Python)          |  | (React)        |  |
|  | - MeanReversion   |  | - Risk checks     |  | Port 3000      |  |
|  +-------------------+  | - IBKR routing    |  +----------------+  |
|                         +-------------------+                      |
+------------------------------------------------------------------+
            |
            | Redis replication / Remote DB connection
            v
+------------------------------------------------------------------+
|                      WORKER SERVER (clone as needed)               |
|                                                                    |
|  +-------------------+  +-------------------+  +----------------+  |
|  | Strategy Runner   |  | ML Inference      |  | GPU Training   |  |
|  | - MLPrediction    |  | (PyTorch)         |  | (offline)      |  |
|  | - PairsTrading    |  |                   |  |                |  |
|  +-------------------+  +-------------------+  +----------------+  |
|                                                                    |
|  Connects to Primary: Redis (6379), PostgreSQL (5432)              |
+------------------------------------------------------------------+
```

### Scaling Model

When primary server is overloaded:
1. Clone repository to new machine
2. Configure to connect to primary Redis/DB
3. Edit config to run subset of strategies
4. Start strategy runner

```yaml
# worker-1.yaml
strategies:
  enabled:
    - ml_prediction_us
    - pairs_trading_tech
  disabled:
    - momentum_breakout  # runs on primary
    - mean_reversion     # runs on primary

connections:
  redis: primary.local:6379
  postgres: primary.local:5432
```

### Service Breakdown

#### 4.1 Market Data Gateway (Python)

**Purpose**: Ingest market data from all providers and publish to Redis Streams.

**Responsibilities:**
- Connect to IBKR TWS/Gateway via `ib_insync`
- Connect to Polygon.io for supplementary US data
- Normalize data formats across providers
- Calculate real-time indicators (MA, RSI, MACD, Bollinger, ATR, etc.)
- Publish tick/bar data to Redis Streams
- Handle reconnection and failover

**Technology:**
- Python 3.11+ with asyncio
- `ib_insync` for IBKR (async-native)
- `pandas` + `numpy` for indicators (vectorized)
- `redis.asyncio` for publishing

**Performance Target:**
- Process 10,000+ ticks/second (sufficient for our symbol count)
- <10ms indicator calculation per tick batch
- If bottlenecked, use `numba` JIT or `numpy` optimizations

```python
# Example: Data gateway interface
class MarketDataGateway:
    async def connect(self) -> None:
        """Connect to all data providers."""

    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribe to real-time data for symbols."""

    async def on_tick(self, tick: Tick) -> None:
        """Process incoming tick, update indicators, publish."""
        indicators = self.indicator_engine.update(tick)
        await self.redis.xadd(
            f"stream:ticks:{tick.exchange}",
            {"symbol": tick.symbol, "price": tick.price, ...}
        )
```

**Indicator Engine:**
```python
class IndicatorEngine:
    def update(self, tick: Tick) -> dict:
        """Update all indicators for symbol, return snapshot."""

    def get_sma(self, symbol: str, period: int) -> float:
        """Get current SMA value."""

    def get_rsi(self, symbol: str, period: int) -> float:
        """Get current RSI value."""

    def get_snapshot(self, symbol: str) -> IndicatorSnapshot:
        """Get all indicators for symbol."""
```

#### 4.2 Discovery Service (Python)

**Purpose**: Identify tradeable opportunities across global markets.

**Responsibilities:**
- Screen universe of symbols based on configurable criteria
- Fundamental filters (market cap, P/E, sector, etc.)
- Technical filters (volume, volatility, trend)
- Liquidity assessment
- Schedule scans per market hours

**Screening Criteria Examples:**
```yaml
discovery:
  us_momentum:
    min_price: 5.0
    max_price: 500.0
    min_avg_volume: 1000000
    min_market_cap: 500000000
    relative_volume_min: 1.5
    atr_percentile_min: 60

  us_mean_reversion:
    min_price: 10.0
    max_price: 200.0
    min_avg_volume: 500000
    rsi_range: [20, 80]  # Look for extremes to fade

  eu_large_cap:
    exchanges: [LSE, XETRA]
    min_market_cap: 1000000000
    min_avg_volume: 100000
```

**Output**: Ranked list of symbols pushed to Strategy Engine.

#### 4.3 Market Regime Detector (Python)

**Purpose**: Identify market conditions to adjust strategy behavior.

**Regimes Detected:**
- **Trend**: Bull, Bear, Sideways
- **Volatility**: Low, Normal, High, Extreme
- **Correlation**: Risk-on, Risk-off
- **Breadth**: Strong, Weak, Divergent

**Indicators Used:**
- VIX and VIX term structure
- Advance/Decline ratios
- New Highs/New Lows
- Sector rotation analysis
- Moving average slopes (SPY, QQQ, IWM)
- Put/Call ratios

**Output Schema:**
```json
{
  "timestamp": "2024-01-15T14:30:00Z",
  "market": "US",
  "regime": {
    "trend": "BULL",
    "trend_strength": 0.72,
    "volatility": "NORMAL",
    "vix": 14.5,
    "breadth": "STRONG",
    "correlation": "RISK_ON"
  },
  "recommendations": {
    "position_size_multiplier": 1.0,
    "favor_long": true,
    "avoid_sectors": ["utilities", "consumer_staples"]
  }
}
```

#### 4.4 Strategy Engine (Python)

**Purpose**: Execute multiple independent trading strategies.

**Key Design Principles:**
- Each strategy instance is isolated (own positions, P&L, risk limits)
- Strategies subscribe to symbols via the Discovery Service
- Strategies receive market data via message bus
- Strategies emit orders to Order Management System
- Same symbol can be traded by multiple strategies simultaneously

**Strategy Interface:**
```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from enum import Enum

class Signal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    CLOSE = "close"

@dataclass
class Order:
    strategy_id: str
    symbol: str
    side: str  # "buy" or "sell"
    quantity: float
    order_type: str  # "market", "limit", "stop", "stop_limit"
    limit_price: Optional[float] = None
    stop_price: Optional[float] = None
    time_in_force: str = "DAY"  # "DAY", "GTC", "IOC", "FOK"

class BaseStrategy(ABC):
    def __init__(self, strategy_id: str, config: dict):
        self.strategy_id = strategy_id
        self.config = config
        self.positions: dict[str, Position] = {}
        self.pending_orders: dict[str, Order] = {}

    @abstractmethod
    def on_bar(self, symbol: str, bar: Bar, indicators: dict) -> Optional[Order]:
        """Called on each new bar. Return Order or None."""
        pass

    @abstractmethod
    def on_tick(self, symbol: str, tick: Tick) -> Optional[Order]:
        """Called on each tick (for high-frequency strategies)."""
        pass

    @abstractmethod
    def on_fill(self, fill: Fill) -> None:
        """Called when an order is filled."""
        pass

    @abstractmethod
    def on_regime_change(self, regime: MarketRegime) -> None:
        """Adjust strategy parameters based on market regime."""
        pass

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)
```

**Strategy Examples (Initial Set):**

| Strategy | Type | Timeframe | Description | Iteration |
|----------|------|-----------|-------------|-----------|
| `MomentumBreakout` | Trend | 5m-1h | Trade breakouts with volume confirmation | 3 |
| `MeanReversion` | Counter-trend | 1m-15m | Fade extreme moves, RSI/BB based | 6 |
| `MLPrediction` | ML | 1h | PyTorch neural net predictions | 12 |
| `PairsTrading` | Market-neutral | 1h-1d | Trade correlated pairs spread | Future |
| `GapFade` | Event | Open | Fade overnight gaps | Future |
| `VWAPReversion` | Intraday | 1m | Trade around VWAP | Future |

**Deferred Strategies:**
- `OptionsWheeling` - Requires options trading support
- `SentimentMomentum` - Requires alternative data feeds

**Concurrent Execution Model:**
```
+------------------+     +------------------+     +------------------+
| Strategy 1       |     | Strategy 2       |     | Strategy 3       |
| MomentumBreakout |     | MeanReversion    |     | MLPrediction     |
| Symbols: 50      |     | Symbols: 100     |     | Symbols: 30      |
| Capital: $50k    |     | Capital: $30k    |     | Capital: $20k    |
+--------+---------+     +--------+---------+     +--------+---------+
         |                        |                        |
         v                        v                        v
+---------------------------------------------------------------+
|                    Order Management System                     |
|  - Aggregates orders from all strategies                      |
|  - Prevents conflicting orders (configurable)                 |
|  - Routes to appropriate broker                               |
+---------------------------------------------------------------+
```

#### 4.5 Order Management System (Python)

**Purpose**: Reliable order routing and execution tracking via IBKR.

**Responsibilities:**
- Receive orders from Strategy Engine via Redis Streams
- Validate against risk limits
- Route to IBKR via `ib_insync`
- Track order lifecycle (pending, filled, partial, cancelled)
- Handle order modifications and cancellations
- Report fills back to strategies via Redis Streams

**Order Flow:**
```
Strategy -> Redis:stream:orders -> OMS -> Risk Check -> IBKR
                                                          |
                                                          v
Strategy <- Redis:stream:fills <- OMS <- Execution Report <-+
```

**Key Features:**
- Order queuing with priority
- Partial fill handling
- Order timeout management
- Bracket orders (entry + stop + target)
- Paper trading mode (simulated fills)

**Technology:**
- Python 3.11+ with asyncio
- `ib_insync` for IBKR order submission
- Redis Streams for order/fill events

```python
class OrderManager:
    async def submit_order(self, order: Order) -> str:
        """Validate and submit order, return order_id."""
        if not self.risk_manager.validate(order):
            raise RiskLimitExceeded(order)

        if self.paper_mode:
            return await self.simulate_fill(order)

        ib_order = self.to_ib_order(order)
        trade = self.ib.placeOrder(order.contract, ib_order)
        return trade.order.orderId
```

#### 4.6 Risk Manager (Python)

**Purpose**: Real-time risk monitoring and enforcement.

**Pre-Trade Risk Checks:**
- Position size limits (per symbol, per sector, total)
- Buying power validation
- Concentration limits
- Correlation exposure
- Options Greeks limits (Delta, Gamma, Vega, Theta)

**Real-Time Monitoring:**
- Portfolio VaR (Value at Risk)
- Max drawdown tracking
- Intraday P&L limits
- Margin utilization
- Sector/geography exposure

**Risk Rules Configuration:**
```yaml
risk:
  global:
    max_portfolio_var_95: 0.02  # 2% daily VaR
    max_drawdown_percent: 0.10  # 10% max drawdown triggers strategy pause
    max_daily_loss: 5000
    max_position_size_percent: 0.05  # 5% per position

  per_strategy:
    MomentumBreakout:
      max_positions: 10
      max_position_value: 10000
      stop_loss_percent: 0.02

  per_symbol:
    default:
      max_shares: 10000
      max_value: 50000
    TSLA:
      max_shares: 500  # Higher volatility, smaller size

  # Options risk rules deferred until options trading enabled
```

#### 4.7 Backtesting Engine (Python)

**Purpose**: Historical strategy testing with production-accurate simulation.

**Key Features:**
- Event-driven simulation matching production architecture
- Realistic fill simulation (slippage, partial fills, latency)
- Multi-strategy backtesting
- Walk-forward optimization
- Monte Carlo analysis
- Transaction cost modeling

**Architecture:**
```
+------------------+
| Historical Data  |
| (TimescaleDB)    |
+--------+---------+
         |
+--------v---------+
| Data Replay      |  <- Simulates real-time data feed
| Engine (Python)  |
+--------+---------+
         |
+--------v---------+
| Strategy Engine  |  <- Same code as production
| (Python)         |
+--------+---------+
         |
+--------v---------+
| Simulated OMS    |  <- Models fills, slippage
| (Python)         |
+--------+---------+
         |
+--------v---------+
| Results Analyzer |  <- pandas, matplotlib
| (Python)         |
+------------------+
```

**Performance Note:** For large backtests, use `multiprocessing` to parallelize
across date ranges or symbols. `numba` JIT can also accelerate hot loops.

**Output Metrics:**
- Total return, CAGR, Sharpe, Sortino, Calmar ratios
- Max drawdown, average drawdown, recovery time
- Win rate, profit factor, expectancy
- Trade distribution analysis
- Regime-based performance breakdown

#### 4.8 Analytics Service (Python)

**Purpose**: Real-time and historical analytics.

**Real-Time Dashboards:**
- Portfolio P&L (total, per strategy, per symbol)
- Position heat map
- Order flow visualization
- Risk metrics dashboard
- Market regime indicators

**Historical Analysis:**
- Trade journal with annotations
- Performance attribution
- Correlation analysis
- Drawdown analysis
- Factor exposure tracking

#### 4.9 Dashboard (React/TypeScript)

**Purpose**: Comprehensive web-based UI.

**Views:**
1. **Overview**: Portfolio summary, P&L, key metrics
2. **Positions**: Active positions with real-time P&L
3. **Orders**: Order book, pending orders, fill history
4. **Strategies**: Per-strategy performance and controls
5. **Discovery**: Screener results, watchlists
6. **Backtesting**: Run backtests, view results
7. **Risk**: Risk dashboard, alerts, limits
8. **Settings**: Configuration management
9. **Logs**: Real-time log viewer with filtering

**Technology:**
- React 18 with TypeScript
- TanStack Query for data fetching
- Zustand for state management
- Recharts/Lightweight Charts for visualizations
- WebSocket for real-time updates
- TailwindCSS for styling

---

## 5. Data Storage Architecture

### Database Selection

| Database | Purpose | Why |
|----------|---------|-----|
| **TimescaleDB** | OHLCV, Ticks | Time-series optimized PostgreSQL, compression, continuous aggregates |
| **PostgreSQL** | Trades, Orders, Config | ACID compliance, complex queries, JSON support |
| **Redis** | Cache, Pub/Sub, Queues | Sub-ms latency, Redis Streams for message bus |
| **ClickHouse** | Analytics (optional) | Column-store for analytical queries |

### Schema Design

```sql
-- TimescaleDB: Market Data
CREATE TABLE ohlcv (
    time        TIMESTAMPTZ NOT NULL,
    symbol      TEXT NOT NULL,
    exchange    TEXT NOT NULL,
    open        DECIMAL(18,8),
    high        DECIMAL(18,8),
    low         DECIMAL(18,8),
    close       DECIMAL(18,8),
    volume      DECIMAL(24,8),
    vwap        DECIMAL(18,8),
    trades      INTEGER
);
SELECT create_hypertable('ohlcv', 'time');
CREATE INDEX idx_ohlcv_symbol_time ON ohlcv (symbol, time DESC);

-- Enable compression for older data
ALTER TABLE ohlcv SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'symbol,exchange'
);
SELECT add_compression_policy('ohlcv', INTERVAL '7 days');

-- PostgreSQL: Trading Data
CREATE TABLE strategies (
    id              UUID PRIMARY KEY,
    name            TEXT NOT NULL,
    type            TEXT NOT NULL,
    config          JSONB NOT NULL,
    status          TEXT DEFAULT 'active',
    allocated_capital DECIMAL(18,2),
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE positions (
    id              UUID PRIMARY KEY,
    strategy_id     UUID REFERENCES strategies(id),
    symbol          TEXT NOT NULL,
    exchange        TEXT NOT NULL,
    side            TEXT NOT NULL,  -- 'long' or 'short'
    quantity        DECIMAL(18,8) NOT NULL,
    avg_entry_price DECIMAL(18,8) NOT NULL,
    current_price   DECIMAL(18,8),
    unrealized_pnl  DECIMAL(18,2),
    realized_pnl    DECIMAL(18,2) DEFAULT 0,
    opened_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE orders (
    id              UUID PRIMARY KEY,
    strategy_id     UUID REFERENCES strategies(id),
    broker_order_id TEXT,
    symbol          TEXT NOT NULL,
    side            TEXT NOT NULL,
    order_type      TEXT NOT NULL,
    quantity        DECIMAL(18,8) NOT NULL,
    limit_price     DECIMAL(18,8),
    stop_price      DECIMAL(18,8),
    filled_quantity DECIMAL(18,8) DEFAULT 0,
    avg_fill_price  DECIMAL(18,8),
    status          TEXT NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE fills (
    id              UUID PRIMARY KEY,
    order_id        UUID REFERENCES orders(id),
    quantity        DECIMAL(18,8) NOT NULL,
    price           DECIMAL(18,8) NOT NULL,
    commission      DECIMAL(18,4),
    fill_time       TIMESTAMPTZ NOT NULL
);

-- Audit trail (event sourcing)
CREATE TABLE events (
    id              BIGSERIAL PRIMARY KEY,
    event_type      TEXT NOT NULL,
    aggregate_type  TEXT NOT NULL,
    aggregate_id    UUID NOT NULL,
    payload         JSONB NOT NULL,
    metadata        JSONB,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_events_aggregate ON events (aggregate_type, aggregate_id, id);
```

### Data Retention Policy

| Data Type | Hot Storage | Warm Storage | Cold Storage |
|-----------|-------------|--------------|--------------|
| Ticks | 7 days | 90 days (compressed) | Archive |
| 1-min bars | 30 days | 2 years (compressed) | Archive |
| Daily bars | Forever | - | - |
| Trades | Forever | - | - |
| Events | 1 year | Forever (compressed) | - |

---

## 6. Message Bus Design

### Redis Streams Architecture

```
+------------------+      +------------------+
| Market Data GW   |----->| stream:ticks     |
+------------------+      +------------------+
                                  |
                    +-------------+-------------+
                    |             |             |
              +-----v-----+ +-----v-----+ +-----v-----+
              | Strategy1 | | Strategy2 | | Risk Mgr  |
              +-----------+ +-----------+ +-----------+

+------------------+      +------------------+
| Strategy Engine  |----->| stream:orders    |
+------------------+      +------------------+
                                  |
                          +-------v-------+
                          | Order Mgmt    |
                          +---------------+

+------------------+      +------------------+
| OMS              |----->| stream:fills     |
+------------------+      +------------------+
                                  |
                    +-------------+-------------+
                    |             |             |
              +-----v-----+ +-----v-----+ +-----v-----+
              | Strategy1 | | Analytics | | Dashboard |
              +-----------+ +-----------+ +-----------+
```

### Stream Topics

| Stream | Publisher | Consumers | Message Rate |
|--------|-----------|-----------|--------------|
| `stream:ticks:{exchange}` | Data Gateway | Strategies, Analytics | High (100k/s) |
| `stream:bars:{timeframe}` | Data Gateway | Strategies | Medium |
| `stream:indicators` | Data Gateway | Strategies | Medium |
| `stream:orders` | Strategies | OMS | Low |
| `stream:fills` | OMS | Strategies, Analytics | Low |
| `stream:regime` | Regime Detector | Strategies | Very Low |
| `stream:alerts` | Risk Manager | Dashboard, Notification | Low |
| `stream:discovery` | Discovery Service | Strategies | Very Low |

### Consumer Groups

Each strategy runs as a separate consumer group to ensure independent processing:

```bash
# Create consumer groups
XGROUP CREATE stream:ticks:us strategy_momentum $ MKSTREAM
XGROUP CREATE stream:ticks:us strategy_meanrev $ MKSTREAM
XGROUP CREATE stream:ticks:us strategy_ml $ MKSTREAM
```

---

## 7. Technology Stack

### All Python (with numpy for performance)

The entire backend is Python. This is sufficient because:

1. **Network latency dominates** - IBKR round-trip is 10-50ms; Python adds <5ms
2. **numpy is C under the hood** - Vectorized indicator calculations are fast
3. **asyncio handles concurrency** - 50k+ events/sec is achievable
4. **Simpler development** - One language, easier debugging, faster iteration

### Performance Optimization Path (if ever needed)

If profiling reveals bottlenecks:

| Bottleneck | Solution |
|------------|----------|
| Indicator calculation slow | Use `numba` JIT compilation |
| Memory pressure | Use `numpy` memory-mapped arrays |
| Backtest too slow | Parallelize with `multiprocessing` |
| ML inference slow | Export to ONNX runtime |

### Component Overview

| Component | Technology | Notes |
|-----------|------------|-------|
| Data Gateway | Python, `ib_insync`, `asyncio` | Async IBKR connection |
| Indicator Engine | Python, `numpy`, `pandas` | Vectorized calculations |
| Order Manager | Python, `ib_insync` | Direct IBKR integration |
| Strategy Engine | Python | Core business logic |
| Risk Manager | Python | Pre-trade validation |
| Backtester | Python, `pandas` | Historical simulation |
| Analytics | Python, `matplotlib` | P&L and reports |
| Dashboard | TypeScript, React | Web frontend |
| ML Training | Python, PyTorch, CUDA | GPU-accelerated |
| ML Inference | Python, PyTorch | CPU sufficient for live |

---

## 8. Horizontal Scaling Design

### Multi-Server Deployment

```
                    +-------------------+
                    |   Load Balancer   |
                    |   (HAProxy)       |
                    +---------+---------+
                              |
        +---------------------+---------------------+
        |                     |                     |
+-------v-------+     +-------v-------+     +-------v-------+
|   Server 1    |     |   Server 2    |     |   Server 3    |
|   (Primary)   |     |   (Worker)    |     |   (Worker)    |
+---------------+     +---------------+     +---------------+
| Data Gateway  |     | Strategy Pod  |     | Strategy Pod  |
| (All feeds)   |     | - Momentum    |     | - ML          |
|               |     | - MeanRev     |     | - Options     |
| OMS           |     |               |     |               |
| Redis Primary |     | Redis Replica |     | Redis Replica |
| TimescaleDB   |     |               |     |               |
+---------------+     +---------------+     +---------------+
        |                     |                     |
        +---------------------+---------------------+
                              |
                    +---------v---------+
                    |   Server 4        |
                    |   (Analytics)     |
                    +-------------------+
                    | Dashboard         |
                    | Backtester        |
                    | PostgreSQL        |
                    +-------------------+
```

### Scaling Strategies

**Vertical Scaling (Single Server):**
- Increase CPU cores for parallel strategy execution
- Add RAM for larger data caches
- Use NVMe SSDs for database performance

**Horizontal Scaling (Multiple Servers):**
- Partition strategies across servers
- Partition by market (US on Server 1, Asia on Server 2)
- Redis Cluster for distributed caching
- TimescaleDB with read replicas

### Resource Requirements (Estimated)

| Scale | Symbols | Servers | CPU Cores | RAM | Storage |
|-------|---------|---------|-----------|-----|---------|
| Small | 500 | 1 | 8 | 32GB | 500GB SSD |
| Medium | 2,000 | 2 | 16 | 64GB | 1TB NVMe |
| Large | 5,000 | 3-4 | 32 | 128GB | 2TB NVMe |
| XL | 10,000+ | 4-6 | 64 | 256GB | 4TB NVMe |

---

## 9. Logging and Observability

### Logging Architecture

```
+------------------+     +------------------+     +------------------+
| Services         |---->| Vector/Fluent    |---->| Loki             |
| (structured logs)|     | (log collector)  |     | (log storage)    |
+------------------+     +------------------+     +------------------+
                                                          |
                                                  +-------v-------+
                                                  | Grafana       |
                                                  | (visualization)|
                                                  +---------------+
```

### Log Levels and Categories

```python
# Structured logging format
{
    "timestamp": "2024-01-15T14:30:00.123456Z",
    "level": "INFO",
    "service": "strategy_engine",
    "strategy_id": "momentum_us_01",
    "symbol": "AAPL",
    "event": "signal_generated",
    "signal": "BUY",
    "confidence": 0.85,
    "indicators": {
        "rsi": 32.5,
        "macd_histogram": 0.45,
        "volume_ratio": 1.8
    },
    "trace_id": "abc123",
    "span_id": "def456"
}
```

### Log Categories

| Category | Level | Retention | Purpose |
|----------|-------|-----------|---------|
| `audit` | INFO | Forever | All trades, orders, fills |
| `signal` | DEBUG | 30 days | Strategy signals |
| `market_data` | TRACE | 7 days | Data quality issues |
| `error` | ERROR | 90 days | All errors |
| `performance` | INFO | 30 days | Latency metrics |

### Metrics (Prometheus)

```yaml
# Key metrics to track
metrics:
  # Data Gateway
  - market_data_latency_ms
  - ticks_processed_total
  - data_gaps_detected

  # Strategy Engine
  - signals_generated_total{strategy, signal_type}
  - strategy_pnl_dollars{strategy}
  - strategy_positions_count{strategy}

  # OMS
  - orders_submitted_total{strategy, order_type}
  - orders_filled_total{strategy}
  - order_latency_ms
  - fill_slippage_bps

  # Risk
  - portfolio_var_95
  - max_drawdown_percent
  - margin_utilization

  # System
  - cpu_usage_percent
  - memory_usage_bytes
  - redis_lag_ms
  - db_query_latency_ms
```

### Alerting Rules

```yaml
alerts:
  - name: HighDrawdown
    condition: max_drawdown_percent > 0.05
    severity: critical
    action: notify + pause_strategies

  - name: DataGap
    condition: data_gaps_detected > 0
    severity: warning
    action: notify

  - name: HighLatency
    condition: order_latency_ms_p99 > 100
    severity: warning
    action: notify

  - name: StrategyFlat
    condition: signals_generated_total rate < 1/hour
    severity: info
    action: notify
```

---

## 10. Testing Strategy

### Test Pyramid

```
                    +-------------+
                    |   E2E       |  <- 10%
                    |   Tests     |
                    +------+------+
                           |
                    +------v------+
                    | Integration |  <- 30%
                    |   Tests     |
                    +------+------+
                           |
                    +------v------+
                    |    Unit     |  <- 60%
                    |   Tests     |
                    +-------------+
```

### Unit Tests

**Coverage Requirements:**
- Strategies: 90%+ coverage
- Indicators: 100% coverage
- Risk calculations: 100% coverage
- Order validation: 100% coverage

**Example Test Structure:**
```python
# tests/unit/strategies/test_momentum.py
import pytest
from strategies.momentum import MomentumStrategy
from tests.fixtures import create_bar_series, create_indicators

class TestMomentumStrategy:
    @pytest.fixture
    def strategy(self):
        return MomentumStrategy(
            strategy_id="test_momentum",
            config={"lookback": 20, "threshold": 0.02}
        )

    def test_generates_buy_signal_on_breakout(self, strategy):
        bars = create_bar_series(trend="up", breakout=True)
        indicators = create_indicators(rsi=45, volume_ratio=2.0)

        order = strategy.on_bar("AAPL", bars[-1], indicators)

        assert order is not None
        assert order.side == "buy"

    def test_no_signal_in_low_volume(self, strategy):
        bars = create_bar_series(trend="up", breakout=True)
        indicators = create_indicators(rsi=45, volume_ratio=0.5)

        order = strategy.on_bar("AAPL", bars[-1], indicators)

        assert order is None

    def test_respects_regime_filter(self, strategy):
        strategy.on_regime_change(MarketRegime(trend="BEAR"))
        bars = create_bar_series(trend="up", breakout=True)
        indicators = create_indicators(rsi=45, volume_ratio=2.0)

        order = strategy.on_bar("AAPL", bars[-1], indicators)

        assert order is None  # No longs in bear market
```

### Integration Tests

**Test Scenarios:**
- Data Gateway -> Strategy Engine flow
- Strategy Engine -> OMS flow
- Full order lifecycle (signal -> fill)
- Risk manager intervention
- Multi-strategy interaction

```python
# tests/integration/test_order_flow.py
@pytest.mark.integration
async def test_full_order_lifecycle():
    # Setup
    data_gateway = MockDataGateway()
    strategy = MomentumStrategy(...)
    oms = MockOMS()

    # Simulate market data
    await data_gateway.publish_tick(Tick(symbol="AAPL", price=150.00))
    await data_gateway.publish_bar(Bar(symbol="AAPL", close=150.50))

    # Wait for signal processing
    await asyncio.sleep(0.1)

    # Verify order was submitted
    orders = await oms.get_pending_orders()
    assert len(orders) == 1
    assert orders[0].symbol == "AAPL"

    # Simulate fill
    await oms.fill_order(orders[0].id, price=150.55, quantity=100)

    # Verify position created
    position = strategy.get_position("AAPL")
    assert position is not None
    assert position.quantity == 100
```

### Backtesting Tests

**Validation Criteria:**
- Results reproducible across runs
- No look-ahead bias
- Realistic fill assumptions
- Transaction costs included

```python
# tests/backtest/test_backtest_integrity.py
def test_no_lookahead_bias():
    """Ensure strategy only sees data up to current bar."""
    backtest = Backtest(
        strategy=MomentumStrategy(...),
        data=historical_data,
        start="2023-01-01",
        end="2023-12-31"
    )

    # Instrument strategy to record seen data
    backtest.strategy.record_seen_data = True

    results = backtest.run()

    for trade in results.trades:
        seen_data = backtest.strategy.seen_data[trade.entry_time]
        assert seen_data.index.max() < trade.entry_time
```

---

## 11. Project Structure

```
axtrade/
├── README.md
├── pyproject.toml                # Python project config (Poetry/pip)
├── docker-compose.yml            # Redis, TimescaleDB, PostgreSQL
├── Makefile                      # Common commands
│
├── src/
│   └── axtrade/                  # Main Python package
│       ├── __init__.py
│       ├── __main__.py           # Entry point: python -m axtrade
│       │
│       ├── gateway/              # Market data ingestion
│       │   ├── __init__.py
│       │   ├── service.py        # Main gateway orchestrator
│       │   ├── ibkr.py           # IBKR adapter (ib_insync)
│       │   ├── polygon.py        # Polygon.io adapter
│       │   └── normalizer.py     # Data normalization
│       │
│       ├── indicators/           # Technical indicators
│       │   ├── __init__.py
│       │   ├── engine.py         # Indicator calculation engine
│       │   ├── trend.py          # SMA, EMA, MACD
│       │   ├── momentum.py       # RSI, Stochastic
│       │   └── volatility.py     # ATR, Bollinger Bands
│       │
│       ├── strategies/           # Trading strategies
│       │   ├── __init__.py
│       │   ├── base.py           # BaseStrategy ABC
│       │   ├── registry.py       # Strategy loader
│       │   ├── momentum.py       # Momentum breakout
│       │   ├── mean_reversion.py # Mean reversion
│       │   └── ml_prediction.py  # ML-based strategy
│       │
│       ├── oms/                  # Order management
│       │   ├── __init__.py
│       │   ├── manager.py        # Order lifecycle
│       │   ├── executor.py       # IBKR order submission
│       │   └── paper.py          # Paper trading simulator
│       │
│       ├── risk/                 # Risk management
│       │   ├── __init__.py
│       │   ├── manager.py        # Risk checks
│       │   ├── limits.py         # Position limits
│       │   └── allocation.py     # Dynamic capital allocation
│       │
│       ├── discovery/            # Symbol discovery
│       │   ├── __init__.py
│       │   ├── service.py        # Discovery orchestrator
│       │   └── screeners.py      # Stock screeners
│       │
│       ├── regime/               # Market regime detection
│       │   ├── __init__.py
│       │   └── detector.py       # Regime classifier
│       │
│       ├── backtesting/          # Backtesting engine
│       │   ├── __init__.py
│       │   ├── engine.py         # Backtest runner
│       │   ├── replay.py         # Data replay
│       │   └── analysis.py       # Results analysis
│       │
│       ├── ml/                   # Machine learning
│       │   ├── __init__.py
│       │   ├── features.py       # Feature engineering
│       │   ├── training.py       # Model training (GPU)
│       │   └── inference.py      # Model inference
│       │
│       ├── analytics/            # Analytics and reporting
│       │   ├── __init__.py
│       │   ├── pnl.py            # P&L calculation
│       │   └── reports.py        # Performance reports
│       │
│       ├── api/                  # REST API for dashboard
│       │   ├── __init__.py
│       │   ├── app.py            # FastAPI app
│       │   └── routes/
│       │       ├── positions.py
│       │       ├── orders.py
│       │       └── strategies.py
│       │
│       ├── cli/                  # Command-line tools
│       │   ├── __init__.py
│       │   └── commands.py       # CLI commands
│       │
│       └── common/               # Shared utilities
│           ├── __init__.py
│           ├── config.py         # Configuration loading
│           ├── logging.py        # Structured logging
│           ├── messaging.py      # Redis Streams helpers
│           ├── db.py             # Database connections
│           └── types.py          # Shared data types
│
├── tests/
│   ├── unit/
│   │   ├── test_indicators.py
│   │   ├── test_strategies.py
│   │   └── test_risk.py
│   ├── integration/
│   │   └── test_order_flow.py
│   └── conftest.py               # Pytest fixtures
│
├── dashboard/                    # React frontend (Iteration 5+)
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/
│   │   ├── hooks/
│   │   └── api/
│   └── tests/
│
├── config/
│   ├── default.yaml              # Default configuration
│   ├── development.yaml          # Dev overrides
│   ├── production.yaml           # Prod overrides
│   ├── worker.yaml               # Worker machine config
│   └── strategies/
│       ├── momentum.yaml
│       └── mean_reversion.yaml
│
├── scripts/
│   ├── setup.sh                  # Initial setup
│   ├── start.sh                  # Start all services
│   └── migrate_db.py             # Database migrations
│
├── deploy/
│   ├── docker/
│   │   ├── Dockerfile
│   │   └── Dockerfile.dashboard
│   └── systemd/
│       ├── axtrade-gateway.service
│       └── axtrade-strategies.service
│
└── notebooks/                    # Jupyter notebooks for analysis
    ├── backtest_analysis.ipynb
    └── ml_experiments.ipynb
```

---

## 12. Iterative Development Plan

### Philosophy

Each iteration delivers a **working, testable system**. No iteration takes more than 1-2 weeks.
Ship early, validate assumptions, then enhance.

---

### Iteration 1: Hello Trading World (Days 1-5)

**Goal:** Prove IBKR connection works, store data, show it on screen.

**Deliverables:**
- [ ] Project structure created
- [ ] Python venv with core dependencies
- [ ] IBKR account opened and API enabled
- [ ] Connect to IBKR paper trading via `ib_insync`
- [ ] Fetch real-time quotes for 5 US symbols
- [ ] Store ticks in Redis
- [ ] Print ticks to console

**Definition of Done:** Running script shows live AAPL price updating.

```bash
$ python -m axtrade.gateway
[2024-01-15 09:30:01] AAPL: 185.23 (+0.15)
[2024-01-15 09:30:02] AAPL: 185.25 (+0.02)
```

---

### Iteration 2: Data Persistence (Days 6-10)

**Goal:** Store historical data, calculate basic indicators.

**Deliverables:**
- [ ] TimescaleDB + PostgreSQL running (Docker)
- [ ] OHLCV schema created
- [ ] Gateway stores 1-min bars to TimescaleDB
- [ ] Basic indicators (SMA, RSI) calculated in Python
- [ ] Indicator values stored alongside bars
- [ ] Simple CLI to query historical data

**Definition of Done:** Can query last 100 bars with indicators for any symbol.

```bash
$ python -m axtrade.cli bars AAPL --limit 10
time                 open    high    low     close   volume   sma_20   rsi_14
2024-01-15 09:30    185.20  185.50  185.10  185.40  125000   184.80   58.3
```

---

### Iteration 3: First Strategy (Days 11-17)

**Goal:** Single strategy generating signals, paper trading.

**Deliverables:**
- [ ] Strategy base class with `on_bar()` interface
- [ ] `MomentumBreakout` strategy implemented
- [ ] Strategy subscribes to Redis Streams
- [ ] Signals logged (no execution yet)
- [ ] Paper trade execution via IBKR paper account
- [ ] Position tracking in PostgreSQL

**Definition of Done:** Strategy opens and closes paper positions automatically.

```
[09:45:00] MomentumBreakout: BUY signal NVDA (RSI=32, breakout confirmed)
[09:45:01] Order submitted: BUY 50 NVDA @ MARKET
[09:45:02] Fill: 50 NVDA @ 485.20
[10:30:00] MomentumBreakout: SELL signal NVDA (target reached)
```

---

### Iteration 4: Risk Management (Days 18-22)

**Goal:** Prevent catastrophic losses, enforce position limits.

**Deliverables:**
- [ ] Risk manager validates orders before submission
- [ ] Position size limits enforced
- [ ] Daily loss limit triggers strategy pause
- [ ] Max drawdown monitoring
- [ ] Risk rules configurable via YAML

**Definition of Done:** System refuses order that would exceed limits.

```
[10:00:00] Order rejected: BUY 1000 TSLA exceeds max_position_value ($50k limit)
[14:30:00] ALERT: Daily loss limit reached (-$5000). Strategies paused.
```

---

### Iteration 5: Basic Dashboard (Days 23-30)

**Goal:** See what's happening without reading logs.

**Deliverables:**
- [ ] React app with Vite
- [ ] WebSocket connection to backend
- [ ] Real-time P&L display
- [ ] Current positions table
- [ ] Recent orders/fills list
- [ ] Basic charts (price + indicators)

**Definition of Done:** Dashboard shows live positions and P&L updating.

---

### Iteration 6: Multi-Strategy (Days 31-38)

**Goal:** Run multiple strategies concurrently with isolated capital.

**Deliverables:**
- [ ] Strategy registry with config-based loading
- [ ] `MeanReversion` strategy added
- [ ] Each strategy has isolated position tracking
- [ ] Capital allocation per strategy
- [ ] Dashboard shows per-strategy P&L

**Definition of Done:** Two strategies trading different symbols simultaneously.

---

### Iteration 7: Dynamic Capital Allocation (Days 39-45)

**Goal:** Adjust strategy allocation based on performance.

**Deliverables:**
- [ ] Rolling performance metrics (Sharpe, drawdown) per strategy
- [ ] Allocation algorithm based on risk-adjusted returns
- [ ] Configurable rebalancing frequency (daily/weekly)
- [ ] Min/max allocation bounds
- [ ] New strategy ramp-up period (start at 25%)

**Definition of Done:** Underperforming strategy automatically gets reduced allocation.

```python
class DynamicAllocator:
    def rebalance(self) -> dict[str, float]:
        """Return new allocation percentages per strategy."""
        for strategy in self.strategies:
            metrics = self.get_rolling_metrics(strategy, days=60)
            sharpe_score = min(2.0, max(0.25, metrics.sharpe / 1.5))
            dd_penalty = 1.0 - (metrics.current_drawdown * 2)
            allocations[strategy] = base * sharpe_score * dd_penalty
        return self.normalize(allocations)
```

---

### Iteration 8: Discovery Service (Days 46-52)

**Goal:** Automatically find tradeable symbols.

**Deliverables:**
- [ ] Stock screener with configurable filters
- [ ] Volume, price, market cap filters
- [ ] Technical filters (RSI extremes, breakout candidates)
- [ ] Scheduled scans (pre-market, intraday)
- [ ] Results published to Redis for strategies

**Definition of Done:** Strategies receive fresh symbol candidates daily.

---

### Iteration 9: Market Regime Detection (Days 53-58)

**Goal:** Strategies adapt to market conditions.

**Deliverables:**
- [ ] VIX-based volatility regime
- [ ] Trend detection (bull/bear/sideways)
- [ ] Regime published to Redis Streams
- [ ] Strategies implement `on_regime_change()`
- [ ] Configurable regime-based parameter adjustments

**Definition of Done:** Momentum strategy reduces position size in high-VIX regime.

---

### Iteration 10: European Markets (Days 59-65)

**Goal:** Trade LSE and XETRA.

**Deliverables:**
- [ ] IBKR data subscriptions for LSE, XETRA
- [ ] Market hours scheduling
- [ ] Currency handling (GBP, EUR positions)
- [ ] Exchange-specific symbol normalization
- [ ] Strategies can filter by exchange

**Definition of Done:** Momentum strategy trades FTSE 100 stocks during London hours.

---

### Iteration 11: Backtesting Engine (Days 66-75)

**Goal:** Test strategies on historical data.

**Deliverables:**
- [ ] Data replay engine (reads from TimescaleDB)
- [ ] Simulated order fills with slippage model
- [ ] Same strategy code runs in backtest and live
- [ ] Performance metrics output (Sharpe, drawdown, etc.)
- [ ] Basic visualization of backtest results

**Definition of Done:** Can backtest momentum strategy on 1 year of data.

---

### Iteration 12: ML Strategy Foundation (Days 76-85)

**Goal:** First ML-based trading strategy.

**Deliverables:**
- [ ] Feature engineering pipeline
- [ ] GPU training with PyTorch
- [ ] Model registry (versioned models)
- [ ] `MLPrediction` strategy using trained model
- [ ] Inference in strategy loop

**Definition of Done:** ML strategy generates signals based on model predictions.

---

### Iteration 13: Asian Markets (Days 86-92)

**Goal:** Trade TSE and HKEX.

**Deliverables:**
- [ ] IBKR data subscriptions for Asia
- [ ] Overnight trading schedule
- [ ] JPY, HKD currency handling
- [ ] Timezone-aware scheduling

**Definition of Done:** System trades continuously across US, EU, Asia sessions.

---

### Iteration 14: Production Hardening (Days 93-105)

**Goal:** Reliable, monitored production system.

**Deliverables:**
- [ ] Prometheus metrics export
- [ ] Grafana dashboards
- [ ] Email alerting for critical events
- [ ] Graceful shutdown/restart
- [ ] Database backups
- [ ] Runbook documentation

**Definition of Done:** System recovers automatically from IBKR disconnection.

---

### Future Iterations (Backlog)

| Iteration | Focus | Priority |
|-----------|-------|----------|
| 15 | Multi-machine distribution | High |
| 16 | Advanced ML (transformers, RL) | Medium |
| 17 | Options trading | Medium |
| 18 | Crypto exchanges | Low |
| 19 | Mobile app notifications | Low |
| 20 | External API access | Low |

---

### Iteration Tracking

| # | Name | Status | Started | Completed |
|---|------|--------|---------|-----------|
| 1 | Hello Trading World | Not Started | - | - |
| 2 | Data Persistence | Not Started | - | - |
| 3 | First Strategy | Not Started | - | - |
| ... | ... | ... | ... | ... |

---

## 13. Configuration Decisions (Resolved)

| Question | Decision | Notes |
|----------|----------|-------|
| Broker Account | IBKR Pro (to be created) | Required for API access |
| Options Trading | Deferred | Focus on equities first |
| ML Infrastructure | NVIDIA GPU(s) | Local training with PyTorch/CUDA |
| Crypto Exchanges | Deferred | Focus on traditional markets first |
| Capital Allocation | Dynamic/performance-based | Sharpe-adjusted with drawdown penalty |
| Notifications | Email + Dashboard | No Telegram/Discord for now |
| Historical Data | Starting fresh | Will collect going forward |
| Primary Server | 32GB RAM, 20 cores | Single machine, clone to scale |
| Market Priority | All major (phased) | US first, then EU, then Asia |

### Remaining Decisions (to be made during implementation)

1. **Rebalancing frequency**: Daily or weekly? (Recommend: weekly to reduce churn)
2. **New strategy ramp-up**: How long at reduced allocation? (Recommend: 30 days at 25%)
3. **Min/max allocation bounds**: What limits? (Recommend: 10% min, 40% max)
4. **IBKR paper vs live transition**: Criteria for going live?

---

## 14. Technology Summary

| Layer | Technology | Rationale |
|-------|------------|-----------|
| **Runtime** | Python 3.11+ | Modern async, pattern matching, speed improvements |
| **Data Ingestion** | `ib_insync`, `asyncio` | Native async IBKR client |
| **Indicators** | `numpy`, `pandas` | Vectorized (C under the hood) |
| **Message Bus** | Redis Streams | Low latency, durability, consumer groups |
| **Strategies** | Python | Flexibility, ML ecosystem |
| **ML Training** | PyTorch, CUDA | GPU acceleration |
| **ML Inference** | PyTorch | CPU sufficient for live trading |
| **Order Management** | `ib_insync` | Direct IBKR integration |
| **Time-series DB** | TimescaleDB | PostgreSQL compatible, compression |
| **Relational DB** | PostgreSQL | ACID, JSON, reliability |
| **Cache** | Redis | Sub-ms access, pub/sub |
| **Frontend** | React, TypeScript, Vite | Modern, typed, fast builds |
| **Charts** | Lightweight Charts | TradingView-quality charts |
| **Monitoring** | Prometheus, Grafana | Industry standard |
| **Logging** | `structlog` | Structured JSON logs |
| **Containers** | Docker Compose | Local services (Redis, DB) |

---

## 15. Risk Considerations

### Technical Risks

| Risk | Mitigation |
|------|------------|
| IBKR API rate limits | Implement request throttling, use snapshots for non-critical symbols |
| Data gaps | Multiple data providers, gap detection alerts |
| Network latency | Place servers near exchange or use colocation for critical markets |
| Database bottleneck | TimescaleDB compression, read replicas, partitioning |

### Operational Risks

| Risk | Mitigation |
|------|------------|
| Strategy bugs | Extensive backtesting, paper trading period, gradual capital increase |
| Excessive drawdown | Hard stop-loss at portfolio level, automatic strategy pause |
| Market flash crash | Circuit breakers, position size limits, diversification |
| Broker outage | Multi-broker support (future), notification system |

### Security Risks

| Risk | Mitigation |
|------|------------|
| API key exposure | Environment variables, secrets manager, key rotation |
| Unauthorized access | VPN, firewall, authentication on all endpoints |
| Data breach | Encryption at rest and in transit, minimal PII |

---

## Appendix A: Glossary

| Term | Definition |
|------|------------|
| **OHLCV** | Open, High, Low, Close, Volume - standard bar data |
| **OMS** | Order Management System |
| **VaR** | Value at Risk - potential loss estimate |
| **Regime** | Market condition classification |
| **Paper Trading** | Simulated trading without real money |
| **Slippage** | Difference between expected and actual fill price |
| **Greeks** | Options risk measures (Delta, Gamma, Vega, Theta) |
| **VWAP** | Volume Weighted Average Price |

---

*Document Version: 2.0*
*Created: 2024*
*Updated: 2025-01*
*Status: Ready for Implementation*

### Change Log

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2024 | Initial design |
| 2.0 | 2025-01 | Python-first approach, iterative development, configuration decisions resolved |
