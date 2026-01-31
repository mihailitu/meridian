# Implementation Plan: Iteration 4 - Backtesting Framework

## Goal
Build an event-driven backtesting engine that reuses existing strategies to validate performance on historical data.

## Definition of Done
```bash
$ python -m axtrade.cli backtest momentum_bt --symbol AAPL --start 2024-01-01 --end 2024-01-31

Backtest Results: momentum_bt (AAPL)
=====================================
Period:           2024-01-01 to 2024-01-31
Total Trades:     12
Win Rate:         58.3%
Total Return:     +4.52%
Sharpe Ratio:     1.84
Max Drawdown:     -2.1%
Profit Factor:    1.65

Trade Log:
time                 side   qty    price    pnl
-------------------  ----   ---    ------   -------
2024-01-03 10:15:00  BUY    100    185.20
2024-01-03 14:30:00  SELL   100    186.50   +130.00
2024-01-05 09:45:00  BUY    100    184.80
...
```

## Architecture

```
CLI (backtest command)
        |
        v
BacktestEngine
        |
   +---------+------------------+
   |         |                  |
   v         v                  v
BarRepository  Strategy    SimulatedBroker
(historical)   (reused)    (fill simulation)
                                |
                                v
                          PerformanceAnalyzer
                          (metrics calculation)
```

## Files to Create/Modify

### New Files
```
src/axtrade/backtest/
    __init__.py
    engine.py              # BacktestEngine - main orchestrator
    broker.py              # SimulatedBroker - order fill simulation
    analytics.py           # PerformanceAnalyzer - metrics calculation
    types.py               # BacktestConfig, BacktestResult, TradeRecord
src/axtrade/cli/backtest.py   # CLI backtest command
tests/unit/test_backtest.py
```

### Modify Existing
```
src/axtrade/common/db.py       # Add get_bars_range() method to BarRepository
src/axtrade/cli/__main__.py    # Add backtest subcommand
```

## Implementation Details

### 1. Backtest Types (backtest/types.py)

```python
@dataclass
class BacktestConfig:
    strategy_type: str
    strategy_id: str
    strategy_config: dict
    symbol: str
    interval: str = "1m"
    start_date: date
    end_date: date
    initial_capital: Decimal = Decimal("100000")
    commission_per_trade: Decimal = Decimal("1.00")

@dataclass
class TradeRecord:
    timestamp: datetime
    side: str  # "BUY" or "SELL"
    quantity: Decimal
    price: Decimal
    commission: Decimal
    pnl: Decimal | None  # None for opening trades

@dataclass
class EquityPoint:
    timestamp: datetime
    equity: Decimal
    drawdown: Decimal

@dataclass
class BacktestResult:
    config: BacktestConfig
    trades: list[TradeRecord]
    equity_curve: list[EquityPoint]

    # Summary metrics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float
    total_return: float
    annualized_return: float
    sharpe_ratio: float
    max_drawdown: float
    profit_factor: float
    avg_trade_pnl: Decimal
    avg_winner: Decimal
    avg_loser: Decimal
```

### 2. Simulated Broker (backtest/broker.py)

```python
class SimulatedBroker:
    """Simulates order execution using historical prices."""

    def __init__(
        self,
        initial_capital: Decimal,
        commission: Decimal = Decimal("1.00"),
        slippage_bps: int = 5,
    ):
        self.cash = initial_capital
        self.commission = commission
        self.slippage_bps = slippage_bps
        self.position: Position | None = None
        self.trades: list[TradeRecord] = []
        self.equity_curve: list[EquityPoint] = []

    def execute_order(
        self,
        order: Order,
        bar: Bar,
        strategy_id: str,
    ) -> Fill | None:
        """Execute order at bar's close price with slippage."""
        # Apply slippage
        # Check sufficient capital for buys
        # Update position
        # Record trade
        # Return Fill

    def update_equity(self, bar: Bar, timestamp: datetime) -> None:
        """Update equity curve with current mark-to-market."""

    def get_position(self, symbol: str) -> Position | None:
        """Get current position for symbol."""
```

### 3. Performance Analyzer (backtest/analytics.py)

```python
class PerformanceAnalyzer:
    """Calculates backtest performance metrics."""

    @staticmethod
    def calculate_metrics(
        trades: list[TradeRecord],
        equity_curve: list[EquityPoint],
        initial_capital: Decimal,
        start_date: date,
        end_date: date,
    ) -> dict:
        """Calculate all performance metrics."""
        return {
            "total_trades": ...,
            "win_rate": ...,
            "total_return": ...,
            "annualized_return": ...,
            "sharpe_ratio": ...,
            "max_drawdown": ...,
            "profit_factor": ...,
            ...
        }

    @staticmethod
    def calculate_sharpe(
        equity_curve: list[EquityPoint],
        risk_free_rate: float = 0.05,
    ) -> float:
        """Calculate annualized Sharpe ratio."""

    @staticmethod
    def calculate_max_drawdown(equity_curve: list[EquityPoint]) -> float:
        """Calculate maximum drawdown percentage."""

    @staticmethod
    def calculate_profit_factor(trades: list[TradeRecord]) -> float:
        """Calculate ratio of gross profits to gross losses."""
```

### 4. Backtest Engine (backtest/engine.py)

```python
from axtrade.strategies import STRATEGY_TYPES, BaseStrategy, BarWithIndicators

class BacktestEngine:
    """Event-driven backtesting engine."""

    def __init__(self, config: BacktestConfig, db_pool: DatabasePool):
        self.config = config
        self.db_pool = db_pool
        self.bar_repo = BarRepository(db_pool)
        self.broker: SimulatedBroker | None = None
        self.strategy: BaseStrategy | None = None

    async def run(self) -> BacktestResult:
        """Run backtest and return results."""
        # 1. Initialize strategy
        self._init_strategy()

        # 2. Initialize broker
        self.broker = SimulatedBroker(
            initial_capital=self.config.initial_capital,
            commission=self.config.commission_per_trade,
        )

        # 3. Load historical bars
        bars = await self.bar_repo.get_bars_range(
            symbol=self.config.symbol,
            interval=self.config.interval,
            start=self.config.start_date,
            end=self.config.end_date,
        )

        # 4. Replay bars through strategy
        for bar_data in bars:
            bar_with_indicators = BarWithIndicators(
                bar=bar_data["bar"],
                sma_20=bar_data.get("sma_20"),
                rsi_14=bar_data.get("rsi_14"),
            )

            # Update strategy position from broker
            position = self.broker.get_position(self.config.symbol)
            if position:
                self.strategy.update_position(position)

            # Get signal from strategy
            order = self.strategy.on_bar(bar_with_indicators)

            # Execute order if any
            if order:
                fill = self.broker.execute_order(
                    order, bar_data["bar"], self.config.strategy_id
                )
                if fill:
                    self.strategy.on_fill(fill)

            # Update equity curve
            self.broker.update_equity(bar_data["bar"], bar_data["bar"].timestamp)

        # 5. Calculate metrics
        metrics = PerformanceAnalyzer.calculate_metrics(
            trades=self.broker.trades,
            equity_curve=self.broker.equity_curve,
            initial_capital=self.config.initial_capital,
            start_date=self.config.start_date,
            end_date=self.config.end_date,
        )

        # 6. Build result
        return BacktestResult(
            config=self.config,
            trades=self.broker.trades,
            equity_curve=self.broker.equity_curve,
            **metrics,
        )

    def _init_strategy(self) -> None:
        """Initialize strategy instance."""
        strategy_cls = STRATEGY_TYPES.get(self.config.strategy_type)
        if not strategy_cls:
            raise ValueError(f"Unknown strategy: {self.config.strategy_type}")
        self.strategy = strategy_cls(
            strategy_id=self.config.strategy_id,
            config=self.config.strategy_config,
        )
```

### 5. BarRepository Extension (common/db.py)

```python
async def get_bars_range(
    self,
    symbol: str,
    interval: str,
    start: date,
    end: date,
) -> list[dict]:
    """Get bars with indicators for a date range.

    Args:
        symbol: Trading symbol
        interval: Bar interval (1m, 5m, etc.)
        start: Start date (inclusive)
        end: End date (inclusive)

    Returns:
        List of dicts with bar and indicator data, ordered by time ASC
    """
    query = """
        SELECT time, symbol, open, high, low, close, volume, sma_20, rsi_14
        FROM bars
        WHERE symbol = $1 AND interval = $2
          AND time >= $3 AND time < $4
        ORDER BY time ASC
    """
    # Convert dates to timestamps
    # Execute query
    # Return list of bar dicts
```

### 6. CLI Backtest Command (cli/backtest.py)

```python
import argparse
from datetime import date
from decimal import Decimal

from axtrade.backtest import BacktestConfig, BacktestEngine
from axtrade.common import DatabasePool, load_config

async def run_backtest(args: argparse.Namespace) -> None:
    """Run backtest with given arguments."""
    config = load_config()

    # Parse strategy config from args or use defaults
    strategy_config = {
        "rsi_oversold": args.rsi_oversold,
        "rsi_overbought": args.rsi_overbought,
        "stop_loss_pct": args.stop_loss,
        "position_size": args.position_size,
    }

    bt_config = BacktestConfig(
        strategy_type=args.strategy,
        strategy_id=f"{args.strategy}_bt",
        strategy_config=strategy_config,
        symbol=args.symbol,
        interval=args.interval,
        start_date=args.start,
        end_date=args.end,
        initial_capital=Decimal(str(args.capital)),
    )

    db_pool = DatabasePool(config.database)
    await db_pool.connect()

    try:
        engine = BacktestEngine(bt_config, db_pool)
        result = await engine.run()
        print_results(result)
    finally:
        await db_pool.disconnect()

def print_results(result: BacktestResult) -> None:
    """Print formatted backtest results."""
    print(f"\nBacktest Results: {result.config.strategy_id} ({result.config.symbol})")
    print("=" * 50)
    print(f"Period:           {result.config.start_date} to {result.config.end_date}")
    print(f"Total Trades:     {result.total_trades}")
    print(f"Win Rate:         {result.win_rate:.1f}%")
    print(f"Total Return:     {result.total_return:+.2f}%")
    print(f"Sharpe Ratio:     {result.sharpe_ratio:.2f}")
    print(f"Max Drawdown:     {result.max_drawdown:.1f}%")
    print(f"Profit Factor:    {result.profit_factor:.2f}")
    # ... more output
```

### 7. CLI Integration (cli/__main__.py)

Add backtest subcommand:
```python
backtest_parser = subparsers.add_parser("backtest", help="Run strategy backtest")
backtest_parser.add_argument("strategy", help="Strategy type (momentum)")
backtest_parser.add_argument("--symbol", required=True, help="Symbol to backtest")
backtest_parser.add_argument("--start", required=True, type=parse_date, help="Start date (YYYY-MM-DD)")
backtest_parser.add_argument("--end", required=True, type=parse_date, help="End date (YYYY-MM-DD)")
backtest_parser.add_argument("--interval", default="1m", help="Bar interval")
backtest_parser.add_argument("--capital", type=float, default=100000, help="Initial capital")
backtest_parser.add_argument("--position-size", type=int, default=100, help="Position size")
backtest_parser.add_argument("--rsi-oversold", type=int, default=40)
backtest_parser.add_argument("--rsi-overbought", type=int, default=70)
backtest_parser.add_argument("--stop-loss", type=float, default=0.02)
```

## Implementation Order

1. **Types**: backtest/types.py with BacktestConfig, TradeRecord, EquityPoint, BacktestResult
2. **Broker**: backtest/broker.py with SimulatedBroker
3. **Analytics**: backtest/analytics.py with PerformanceAnalyzer
4. **DB Extension**: Add get_bars_range() to BarRepository
5. **Engine**: backtest/engine.py with BacktestEngine
6. **CLI**: cli/backtest.py and update __main__.py
7. **Tests**: Unit tests for broker, analytics, engine

## Test Cases

### SimulatedBroker Tests
- Execute buy order reduces cash, creates position
- Execute sell order closes position, records P&L
- Slippage applied correctly
- Commission deducted
- Insufficient capital rejects order
- Equity curve updated on each bar

### PerformanceAnalyzer Tests
- Win rate calculation
- Sharpe ratio calculation
- Max drawdown calculation
- Profit factor calculation
- Edge cases: no trades, all winners, all losers

### BacktestEngine Tests
- Loads correct date range
- Strategy receives bars in order
- Orders executed and positions tracked
- Final result contains all metrics

## Verification Steps

1. Collect some historical data:
   ```bash
   make infra
   make run &
   make run-aggregator &
   # Wait 5-10 minutes for bars to accumulate
   ```

2. Run backtest:
   ```bash
   python -m axtrade.cli backtest momentum --symbol AAPL --start 2024-01-20 --end 2024-01-23
   ```

3. Verify output shows trades and metrics

4. Run tests:
   ```bash
   pytest tests/unit/test_backtest.py -v
   ```

## Key Design Decisions

1. **Reuse existing strategies**: BacktestEngine uses the same BaseStrategy classes as live trading
2. **Fill at close price**: Simplest model, orders fill at bar close with slippage
3. **Single symbol per backtest**: Keeps initial implementation simple
4. **In-memory equity curve**: Sufficient for single-symbol backtests
5. **No lookahead bias**: Bars processed in chronological order, strategy only sees current bar
