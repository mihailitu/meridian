# Implementation Plan: Iteration 3 - First Strategy

## Goal
Single strategy generating signals and executing paper trades via IBKR.

## Definition of Done
```
[09:45:00] MomentumBreakout: BUY signal NVDA (RSI=32.5, breakout confirmed)
[09:45:01] Order submitted: BUY 50 NVDA @ MARKET
[09:45:02] Fill: 50 NVDA @ 485.20
[10:30:00] MomentumBreakout: Position update NVDA: qty=50, entry=485.20, pnl=+$125.00
```

## Architecture

```
stream:bars:1m:us
       |
       v
BarConsumer (new)
       |
       v
StrategyRunner -----> BaseStrategy.on_bar()
       |                     |
       |              MomentumBreakout
       |                     |
       v                     v
OrderManager <-------- Order (signal)
       |
       v
  [Paper Mode]              [Live Mode - future]
  SimulatedFills            IBKR via ib_insync
       |
       v
stream:fills
       |
       v
StrategyRunner.on_fill() -> Position updates
       |
       v
PositionRepository -> PostgreSQL
```

## Files to Create/Modify

### New Files
```
src/axtrade/strategies/
    __init__.py
    base.py                 # BaseStrategy ABC, Signal enum
    momentum.py             # MomentumBreakout strategy
    runner.py               # StrategyRunner service
    __main__.py             # Entry point: python -m axtrade.strategies

src/axtrade/oms/
    __init__.py
    types.py                # Order, Fill, Position dataclasses
    manager.py              # OrderManager with paper trading
    repository.py           # PositionRepository, OrderRepository

scripts/init-db.sql         # Add positions, orders, fills tables

tests/unit/test_strategies.py
tests/unit/test_oms.py
```

### Modify Existing
```
src/axtrade/common/config.py       # Add StrategyConfig, OMSConfig
src/axtrade/common/__init__.py     # Export new classes
src/axtrade/common/messaging.py    # Add BarConsumer, FillPublisher
config/default.yaml                # Add strategies, oms sections
Makefile                           # Add run-strategy target
```

## Implementation Details

### 1. Database Schema Additions (scripts/init-db.sql)

```sql
-- Positions table
CREATE TABLE positions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     VARCHAR(50)     NOT NULL,
    symbol          VARCHAR(20)     NOT NULL,
    side            VARCHAR(10)     NOT NULL,  -- 'long' or 'short'
    quantity        DECIMAL(18,8)   NOT NULL,
    avg_entry_price DECIMAL(18,6)   NOT NULL,
    current_price   DECIMAL(18,6),
    unrealized_pnl  DECIMAL(18,2),
    realized_pnl    DECIMAL(18,2)   DEFAULT 0,
    opened_at       TIMESTAMPTZ     DEFAULT NOW(),
    closed_at       TIMESTAMPTZ,
    updated_at      TIMESTAMPTZ     DEFAULT NOW(),
    UNIQUE(strategy_id, symbol)
);

CREATE INDEX idx_positions_strategy ON positions (strategy_id);
CREATE INDEX idx_positions_symbol ON positions (symbol);

-- Orders table
CREATE TABLE orders (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strategy_id     VARCHAR(50)     NOT NULL,
    symbol          VARCHAR(20)     NOT NULL,
    side            VARCHAR(10)     NOT NULL,  -- 'buy' or 'sell'
    order_type      VARCHAR(20)     NOT NULL,  -- 'market', 'limit', 'stop'
    quantity        DECIMAL(18,8)   NOT NULL,
    limit_price     DECIMAL(18,6),
    stop_price      DECIMAL(18,6),
    filled_quantity DECIMAL(18,8)   DEFAULT 0,
    avg_fill_price  DECIMAL(18,6),
    status          VARCHAR(20)     NOT NULL,  -- 'pending', 'filled', 'partial', 'cancelled'
    created_at      TIMESTAMPTZ     DEFAULT NOW(),
    updated_at      TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX idx_orders_strategy ON orders (strategy_id);
CREATE INDEX idx_orders_status ON orders (status);

-- Fills table
CREATE TABLE fills (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID            REFERENCES orders(id),
    strategy_id     VARCHAR(50)     NOT NULL,
    symbol          VARCHAR(20)     NOT NULL,
    side            VARCHAR(10)     NOT NULL,
    quantity        DECIMAL(18,8)   NOT NULL,
    price           DECIMAL(18,6)   NOT NULL,
    commission      DECIMAL(18,4)   DEFAULT 0,
    filled_at       TIMESTAMPTZ     DEFAULT NOW()
);

CREATE INDEX idx_fills_order ON fills (order_id);
CREATE INDEX idx_fills_strategy ON fills (strategy_id);
```

### 2. OMS Types (oms/types.py)

```python
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

class OrderSide(Enum):
    BUY = "buy"
    SELL = "sell"

class OrderType(Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"

class OrderStatus(Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"

@dataclass
class Order:
    strategy_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    id: UUID = field(default_factory=uuid4)
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: Decimal = Decimal("0")
    avg_fill_price: Optional[Decimal] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

@dataclass
class Fill:
    order_id: UUID
    strategy_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    commission: Decimal = Decimal("0")
    id: UUID = field(default_factory=uuid4)
    filled_at: datetime = field(default_factory=lambda: datetime.now(UTC))

@dataclass
class Position:
    strategy_id: str
    symbol: str
    side: str  # 'long' or 'short'
    quantity: Decimal
    avg_entry_price: Decimal
    current_price: Optional[Decimal] = None
    unrealized_pnl: Optional[Decimal] = None
    realized_pnl: Decimal = Decimal("0")
    id: Optional[UUID] = None
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
```

### 3. Strategy Base Class (strategies/base.py)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from axtrade.common import Bar
from axtrade.oms import Order, Position

class Signal(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    CLOSE = "close"

@dataclass
class BarWithIndicators:
    bar: Bar
    sma_20: Optional[float] = None
    rsi_14: Optional[float] = None

class BaseStrategy(ABC):
    def __init__(self, strategy_id: str, config: dict):
        self.strategy_id = strategy_id
        self.config = config
        self.positions: dict[str, Position] = {}
        self.enabled = True

    @abstractmethod
    def on_bar(self, data: BarWithIndicators) -> Optional[Order]:
        """Process a bar and optionally return an order."""
        pass

    def on_fill(self, fill: Fill) -> None:
        """Handle a fill notification. Override for custom logic."""
        pass

    def get_position(self, symbol: str) -> Optional[Position]:
        return self.positions.get(symbol)

    def update_position(self, position: Position) -> None:
        if position.quantity == 0:
            self.positions.pop(position.symbol, None)
        else:
            self.positions[position.symbol] = position

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy name for logging."""
        pass
```

### 4. Momentum Strategy (strategies/momentum.py)

```python
class MomentumBreakout(BaseStrategy):
    """
    Breakout strategy using RSI and price action.

    Entry (long):
    - RSI < 40 (oversold bounce)
    - Price > SMA_20 (trend confirmation)
    - Volume confirmation (handled by aggregator)

    Exit:
    - RSI > 70 (overbought)
    - Price < SMA_20 (trend reversal)
    - Stop loss: 2% below entry
    """

    def __init__(self, strategy_id: str, config: dict):
        super().__init__(strategy_id, config)
        self.rsi_oversold = config.get("rsi_oversold", 40)
        self.rsi_overbought = config.get("rsi_overbought", 70)
        self.stop_loss_pct = config.get("stop_loss_pct", 0.02)
        self.position_size = Decimal(str(config.get("position_size", 100)))

    @property
    def name(self) -> str:
        return "MomentumBreakout"

    def on_bar(self, data: BarWithIndicators) -> Optional[Order]:
        bar = data.bar
        position = self.get_position(bar.symbol)

        # Need indicators to make decisions
        if data.sma_20 is None or data.rsi_14 is None:
            return None

        # Check for exit first if we have a position
        if position:
            return self._check_exit(bar, data, position)

        # Check for entry
        return self._check_entry(bar, data)

    def _check_entry(self, bar: Bar, data: BarWithIndicators) -> Optional[Order]:
        # Long entry: RSI oversold + price above SMA
        if data.rsi_14 < self.rsi_oversold and bar.close > data.sma_20:
            return Order(
                strategy_id=self.strategy_id,
                symbol=bar.symbol,
                side=OrderSide.BUY,
                quantity=self.position_size,
                order_type=OrderType.MARKET,
            )
        return None

    def _check_exit(self, bar: Bar, data: BarWithIndicators, position: Position) -> Optional[Order]:
        # Exit on overbought
        if data.rsi_14 > self.rsi_overbought:
            return self._create_close_order(position)

        # Exit on trend reversal
        if bar.close < data.sma_20:
            return self._create_close_order(position)

        # Stop loss check
        if position.avg_entry_price:
            loss_pct = (bar.close - float(position.avg_entry_price)) / float(position.avg_entry_price)
            if loss_pct < -self.stop_loss_pct:
                return self._create_close_order(position)

        return None

    def _create_close_order(self, position: Position) -> Order:
        return Order(
            strategy_id=self.strategy_id,
            symbol=position.symbol,
            side=OrderSide.SELL,
            quantity=position.quantity,
            order_type=OrderType.MARKET,
        )
```

### 5. Order Manager (oms/manager.py)

```python
class OrderManager:
    """Manages order submission and fill simulation in paper mode."""

    def __init__(self, config: OMSConfig, pool: DatabasePool):
        self.config = config
        self.paper_mode = config.paper_mode
        self._pool = pool
        self._order_repo: OrderRepository
        self._position_repo: PositionRepository
        self._fill_publisher: FillPublisher
        self._pending_orders: dict[UUID, Order] = {}
        self.logger = get_logger("oms")

    async def connect(self) -> None:
        self._order_repo = OrderRepository(self._pool)
        self._position_repo = PositionRepository(self._pool)
        # FillPublisher for notifying strategies

    async def submit_order(self, order: Order) -> UUID:
        """Submit an order. In paper mode, simulates immediate fill."""
        await self._order_repo.insert(order)
        self.logger.info(
            "Order submitted",
            order_id=str(order.id),
            symbol=order.symbol,
            side=order.side.value,
            quantity=str(order.quantity),
        )

        if self.paper_mode:
            await self._simulate_fill(order)

        return order.id

    async def _simulate_fill(self, order: Order) -> None:
        """Simulate a fill for paper trading."""
        # Get current price from Redis or use a mock price
        fill_price = await self._get_fill_price(order)

        # Add small slippage for realism
        slippage = Decimal("0.01") * (1 if order.side == OrderSide.BUY else -1)
        fill_price = fill_price + slippage

        fill = Fill(
            order_id=order.id,
            strategy_id=order.strategy_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            commission=Decimal("1.00"),  # Flat commission for paper
        )

        # Update order status
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.avg_fill_price = fill_price
        await self._order_repo.update(order)

        # Record fill
        await self._order_repo.insert_fill(fill)

        # Update position
        await self._update_position(fill)

        # Publish fill notification
        await self._fill_publisher.publish(fill)

        self.logger.info(
            "Fill executed",
            order_id=str(order.id),
            symbol=order.symbol,
            price=str(fill_price),
            quantity=str(order.quantity),
        )

    async def _update_position(self, fill: Fill) -> None:
        """Update position based on fill."""
        position = await self._position_repo.get(fill.strategy_id, fill.symbol)

        if position is None:
            # New position
            position = Position(
                strategy_id=fill.strategy_id,
                symbol=fill.symbol,
                side="long" if fill.side == OrderSide.BUY else "short",
                quantity=fill.quantity,
                avg_entry_price=fill.price,
            )
        else:
            # Update existing position
            if fill.side == OrderSide.BUY:
                # Adding to long or closing short
                new_qty = position.quantity + fill.quantity
                if position.side == "long":
                    # Average up/down
                    total_cost = position.quantity * position.avg_entry_price + fill.quantity * fill.price
                    position.avg_entry_price = total_cost / new_qty
                position.quantity = new_qty
            else:
                # Reducing position
                position.quantity = position.quantity - fill.quantity

        if position.quantity == 0:
            position.closed_at = datetime.now(UTC)

        await self._position_repo.upsert(position)
```

### 6. Strategy Runner (strategies/runner.py)

```python
class StrategyRunner:
    """Runs strategies by consuming bars and routing orders."""

    def __init__(self, config: Config):
        self.config = config
        self.logger = get_logger("strategy_runner")

        self._bar_consumer: BarConsumer
        self._order_manager: OrderManager
        self._strategies: dict[str, BaseStrategy] = {}
        self._running = False

    async def start(self) -> None:
        self.logger.info("Starting strategy runner...")

        # Connect to database
        self._db_pool = DatabasePool(self.config.database)
        await self._db_pool.connect()

        # Initialize order manager
        self._order_manager = OrderManager(self.config.oms, self._db_pool)
        await self._order_manager.connect()

        # Load strategies
        self._load_strategies()

        # Connect bar consumer
        self._bar_consumer = BarConsumer(self.config.redis, self.config.strategies)
        await self._bar_consumer.connect()

        self._running = True
        await self._consume_loop()

    def _load_strategies(self) -> None:
        """Load enabled strategies from config."""
        for strat_config in self.config.strategies.enabled:
            strategy = self._create_strategy(strat_config)
            self._strategies[strategy.strategy_id] = strategy
            self.logger.info("Loaded strategy", name=strategy.name, id=strategy.strategy_id)

    async def _consume_loop(self) -> None:
        """Main loop consuming bars and feeding strategies."""
        consumer_name = f"strategy-runner-{uuid.uuid4().hex[:8]}"

        async for bar_data in self._bar_consumer.consume(consumer_name):
            if not self._running:
                break

            for strategy in self._strategies.values():
                if not strategy.enabled:
                    continue

                try:
                    order = strategy.on_bar(bar_data)
                    if order:
                        self._log_signal(strategy, bar_data, order)
                        await self._order_manager.submit_order(order)
                except Exception as e:
                    self.logger.error(
                        "Strategy error",
                        strategy=strategy.name,
                        error=str(e),
                    )

    def _log_signal(self, strategy: BaseStrategy, data: BarWithIndicators, order: Order) -> None:
        """Log a trading signal."""
        bar = data.bar
        print(
            f"[{bar.timestamp:%H:%M:%S}] {strategy.name}: "
            f"{order.side.value.upper()} signal {bar.symbol} "
            f"(RSI={data.rsi_14:.1f}, price={bar.close:.2f})"
        )
```

### 7. Config Additions (config.py)

```python
@dataclass
class OMSConfig:
    paper_mode: bool = True
    slippage_bps: int = 10  # basis points

@dataclass
class StrategyInstanceConfig:
    type: str  # "momentum", "mean_reversion", etc.
    id: str
    enabled: bool = True
    config: dict = field(default_factory=dict)

@dataclass
class StrategiesConfig:
    enabled: list[StrategyInstanceConfig] = field(default_factory=list)
    bar_stream: str = "stream:bars:1m:us"
    consumer_group: str = "strategies"
```

### 8. Config YAML Additions (default.yaml)

```yaml
oms:
  paper_mode: true
  slippage_bps: 10

strategies:
  bar_stream: "stream:bars:1m:us"
  consumer_group: "strategies"
  enabled:
    - type: momentum
      id: momentum_us_01
      enabled: true
      config:
        rsi_oversold: 40
        rsi_overbought: 70
        stop_loss_pct: 0.02
        position_size: 100
```

### 9. Makefile Addition

```makefile
run-strategy:
	.venv/bin/python -m axtrade.strategies
```

## Implementation Order

1. **OMS Types**: Create oms/types.py with Order, Fill, Position dataclasses
2. **Database Schema**: Update init-db.sql with positions, orders, fills tables
3. **Config**: Add OMSConfig, StrategiesConfig to config.py, update default.yaml
4. **Repositories**: Create oms/repository.py with PositionRepository, OrderRepository
5. **Order Manager**: Create oms/manager.py with paper trading simulation
6. **Strategy Base**: Create strategies/base.py with BaseStrategy ABC
7. **Momentum Strategy**: Create strategies/momentum.py
8. **Bar Consumer**: Add BarConsumer to common/messaging.py
9. **Strategy Runner**: Create strategies/runner.py service
10. **Entry Point**: Create strategies/__main__.py
11. **Tests**: Unit tests for strategy logic and OMS
12. **Makefile**: Add run-strategy target

## Verification Steps

1. Start infrastructure: `make infra`
2. Run gateway: `make run` (terminal 1)
3. Run aggregator: `make run-aggregator` (terminal 2)
4. Wait ~1-2 minutes for indicators to warm up (20+ bars)
5. Run strategy: `make run-strategy` (terminal 3)
6. Observe signals and fills in console output
7. Query positions: `python -m axtrade.cli positions`
8. Run tests: `pytest tests/unit/test_strategies.py tests/unit/test_oms.py -v`

## Key Design Decisions

1. **Paper mode first**: All fills simulated, no IBKR connection needed yet
2. **Strategies consume bars, not ticks**: Lower frequency, includes indicators
3. **Single strategy type initially**: MomentumBreakout proves the architecture
4. **Positions in DB**: Survives restarts, enables CLI queries
5. **Fill publisher for async notification**: Strategies can react to fills
6. **Strategy isolation**: Each strategy has its own positions, no cross-contamination
