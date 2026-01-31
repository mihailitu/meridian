# Iteration 11: Performance Analytics

**Status: COMPLETE**

## Goal
Advanced portfolio and strategy performance analytics with rolling metrics, drawdown analysis, and trade statistics.

## Key Components

1. **Rolling Performance Metrics**
   - Rolling Sharpe ratio (configurable window)
   - Rolling Sortino ratio (downside deviation)
   - Rolling volatility
   - Rolling beta (vs benchmark)

2. **Drawdown Analysis**
   - Current drawdown
   - Maximum drawdown
   - Drawdown duration
   - Recovery time tracking
   - Underwater equity curve

3. **Trade Statistics**
   - Win rate by strategy
   - Average win/loss ratio
   - Profit factor
   - Expectancy
   - Trade duration distribution
   - Time-of-day performance

4. **Strategy Analytics**
   - Per-strategy P&L breakdown
   - Strategy correlation matrix
   - Performance attribution
   - Risk-adjusted returns by strategy

## Architecture

```
TradeRepository (existing)
        |
        v
PerformanceAnalyzer -----> AnalyticsCache (in-memory)
        |                         |
        v                         v
+-------------------+    +------------------+
| RollingMetrics    |    | REST API         |
| DrawdownTracker   |    | GET /api/analytics/*
| TradeStats        |    +------------------+
| StrategyAnalytics |
+-------------------+
```

## Files to Create

```
src/axtrade/analytics/
    __init__.py
    metrics.py          # Rolling Sharpe, Sortino, volatility
    drawdown.py         # Drawdown tracking and analysis
    trades.py           # Trade statistics
    strategy.py         # Strategy-level analytics
    cache.py            # Analytics cache with TTL

src/axtrade/api/routes/analytics.py   # Analytics endpoints
```

## Files to Modify

```
src/axtrade/api/app.py              # Register analytics routes
src/axtrade/web/static/index.html   # Analytics section
src/axtrade/web/static/app.js       # Load and display analytics
src/axtrade/web/static/styles.css   # Analytics styling
```

## Implementation Details

### 1. Rolling Metrics (metrics.py)

```python
@dataclass
class RollingMetrics:
    sharpe_ratio: float | None
    sortino_ratio: float | None
    volatility: float | None
    beta: float | None
    window_days: int
    calculated_at: datetime

def calculate_sharpe_ratio(
    returns: list[float],
    risk_free_rate: float = 0.0,
    annualization_factor: float = 252,
) -> float | None

def calculate_sortino_ratio(
    returns: list[float],
    risk_free_rate: float = 0.0,
    annualization_factor: float = 252,
) -> float | None

def calculate_rolling_volatility(
    returns: list[float],
    annualization_factor: float = 252,
) -> float | None
```

### 2. Drawdown Tracker (drawdown.py)

```python
@dataclass
class DrawdownInfo:
    current_drawdown: float        # Current % below peak
    max_drawdown: float            # Maximum % drawdown
    peak_value: Decimal            # High water mark
    trough_value: Decimal          # Lowest point in current DD
    peak_date: datetime
    trough_date: datetime | None
    drawdown_duration_days: int    # Days in current drawdown
    recovery_days: int | None      # Days to recover (if recovered)

class DrawdownTracker:
    def update(self, equity: Decimal, timestamp: datetime) -> DrawdownInfo
    def get_drawdown_periods(self) -> list[DrawdownPeriod]
    def get_underwater_curve(self) -> list[tuple[datetime, float]]
```

### 3. Trade Statistics (trades.py)

```python
@dataclass
class TradeStats:
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    avg_win: Decimal
    avg_loss: Decimal
    avg_win_loss_ratio: float
    profit_factor: float
    expectancy: Decimal
    avg_trade_duration: timedelta
    largest_win: Decimal
    largest_loss: Decimal
    consecutive_wins: int
    consecutive_losses: int

def calculate_trade_stats(trades: list[TradeRecord]) -> TradeStats

@dataclass
class TimeAnalysis:
    hourly_pnl: dict[int, Decimal]      # Hour -> P&L
    daily_pnl: dict[str, Decimal]       # Day name -> P&L
    monthly_pnl: dict[str, Decimal]     # Month -> P&L

def analyze_time_performance(trades: list[TradeRecord]) -> TimeAnalysis
```

### 4. Strategy Analytics (strategy.py)

```python
@dataclass
class StrategyPerformance:
    strategy_id: str
    total_pnl: Decimal
    trade_count: int
    win_rate: float
    sharpe_ratio: float | None
    max_drawdown: float
    avg_trade_pnl: Decimal

def calculate_strategy_performance(
    trades: list[TradeRecord],
    equity_curve: list[EquityPoint],
) -> dict[str, StrategyPerformance]

def calculate_correlation_matrix(
    strategy_returns: dict[str, list[float]],
) -> dict[tuple[str, str], float]
```

### 5. Analytics Cache (cache.py)

```python
class AnalyticsCache:
    def __init__(self, ttl_seconds: int = 60):
        self._cache: dict[str, tuple[Any, datetime]] = {}
        self._ttl = ttl_seconds

    def get(self, key: str) -> Any | None
    def set(self, key: str, value: Any) -> None
    def invalidate(self, key: str) -> None
    def clear(self) -> None
```

### 6. API Endpoints (routes/analytics.py)

```python
# GET /api/analytics/summary
# Returns overall portfolio performance summary

# GET /api/analytics/rolling?window=30
# Returns rolling metrics for specified window

# GET /api/analytics/drawdown
# Returns current drawdown info and history

# GET /api/analytics/trades
# Returns trade statistics

# GET /api/analytics/trades/time
# Returns time-based performance analysis

# GET /api/analytics/strategies
# Returns per-strategy performance

# GET /api/analytics/correlation
# Returns strategy correlation matrix
```

### 7. Frontend Updates

Add analytics section to dashboard:
- Performance summary cards (Sharpe, Sortino, Max DD)
- Rolling metrics chart
- Drawdown chart (underwater curve)
- Trade statistics table
- Strategy breakdown table

## Implementation Order

1. Core metrics (Sharpe, Sortino, volatility)
2. Drawdown tracker
3. Trade statistics
4. Strategy analytics
5. Analytics cache
6. API endpoints
7. Frontend updates
8. Tests

## Verification

1. Run backtest to generate trade data
2. Query analytics endpoints
3. Verify calculations match expected values
4. Check frontend displays correctly
5. Run tests: `pytest tests/unit/test_analytics.py -v`

## Completion Summary

Implemented all core analytics functionality:

### Files Created
- `src/axtrade/analytics/__init__.py` - Module exports
- `src/axtrade/analytics/metrics.py` - Sharpe ratio, Sortino ratio, volatility, annualized return, rolling metrics
- `src/axtrade/analytics/drawdown.py` - DrawdownTracker, DrawdownInfo, DrawdownPeriod, max drawdown
- `src/axtrade/analytics/trades.py` - TradeStats, TradeRecord, TimeAnalysis, trade statistics
- `src/axtrade/analytics/strategy.py` - StrategyPerformance, PortfolioSummary, correlation matrix
- `src/axtrade/api/routes/analytics.py` - REST API endpoints for analytics
- `tests/unit/test_analytics.py` - 35 unit tests

### Files Modified
- `src/axtrade/oms/repository.py` - Added `get_daily_pnl_series()` method
- `src/axtrade/api/app.py` - Registered analytics routes
- `src/axtrade/web/static/index.html` - Added analytics cards section
- `src/axtrade/web/static/app.js` - Added loadAnalytics() function
- `src/axtrade/web/static/styles.css` - Added analytics card styling

### Test Results
- 35 new analytics tests
- 317 total tests passing

### Notes
- Cache functionality deferred (not needed for v1)
- Beta calculation deferred (requires benchmark data)
- Frontend shows key metrics; charts deferred for later iteration
