# Implementation Plan: Iteration 5 - Live Trading Integration

## Goal
Connect OrderManager to IBKR for real order execution, with proper order state synchronization, partial fill handling, and pre-trade risk checks.

## Definition of Done
```bash
# In config/default.yaml
oms:
  paper_mode: false  # Switch to live

# Run strategy with live execution
$ make run-strategy
2024-01-15 09:30:15 [info] Order submitted to IBKR: BUY 100 AAPL @ MARKET
2024-01-15 09:30:15 [info] Order accepted: id=12345
2024-01-15 09:30:16 [info] Fill received: 100 AAPL @ 185.52
2024-01-15 09:30:16 [info] Position updated: AAPL long 100 @ 185.52
```

## Architecture

```
Strategy
    |
    v
OrderManager
    |
    +--[paper_mode=true]--> SimulatedBroker (existing)
    |
    +--[paper_mode=false]--> IBKRBroker (new)
                                |
                                v
                            ib_insync
                                |
                                v
                              IBKR TWS/Gateway
```

## Files to Create/Modify

### New Files
```
src/axtrade/oms/broker.py          # BrokerProtocol, IBKRBroker
src/axtrade/oms/risk.py            # RiskManager with pre-trade checks
tests/unit/test_risk.py
tests/unit/test_oms_broker.py
```

### Modify Existing
```
src/axtrade/oms/manager.py         # Refactor to use broker protocol
src/axtrade/oms/__init__.py        # Export new classes
src/axtrade/common/config.py       # Extend OMSConfig with risk settings
config/default.yaml                # Add risk config section
```

## Implementation Details

### 1. Broker Protocol (oms/broker.py)

```python
from typing import Protocol, Optional
from axtrade.oms import Order, Fill, Position

class BrokerProtocol(Protocol):
    """Protocol for order execution brokers."""

    async def connect(self) -> None:
        """Connect to broker."""
        ...

    async def disconnect(self) -> None:
        """Disconnect from broker."""
        ...

    async def submit_order(self, order: Order) -> str:
        """Submit order, return broker order ID."""
        ...

    async def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel an order."""
        ...

    async def get_positions(self) -> list[Position]:
        """Get current positions from broker."""
        ...

    def set_fill_callback(self, callback: Callable[[Fill], Awaitable[None]]) -> None:
        """Set callback for fill notifications."""
        ...


class PaperBroker:
    """Paper trading broker (existing logic extracted)."""

    def __init__(self, slippage_bps: int = 10):
        self.slippage_bps = slippage_bps
        self._last_prices: dict[str, Decimal] = {}
        self._fill_callback: Optional[Callable] = None

    async def connect(self) -> None:
        pass

    async def disconnect(self) -> None:
        pass

    async def submit_order(self, order: Order) -> str:
        """Simulate immediate fill."""
        # Use last known price + slippage
        # Generate fill
        # Call fill callback
        return str(order.id)

    def update_price(self, symbol: str, price: Decimal) -> None:
        """Update price for paper fills."""
        self._last_prices[symbol] = price


class IBKRBroker:
    """Interactive Brokers order execution."""

    def __init__(self, config: IBKRConfig):
        self.config = config
        self._ib: Optional[IB] = None
        self._fill_callback: Optional[Callable] = None
        self._order_map: dict[int, UUID] = {}  # IBKR trade ID -> our order ID

    async def connect(self) -> None:
        """Connect to TWS/Gateway."""
        self._ib = IB()
        await self._ib.connectAsync(
            host=self.config.host,
            port=self.config.port,
            clientId=self.config.client_id,
        )
        # Subscribe to order events
        self._ib.orderStatusEvent += self._on_order_status
        self._ib.execDetailsEvent += self._on_execution

    async def disconnect(self) -> None:
        if self._ib:
            self._ib.disconnect()

    async def submit_order(self, order: Order) -> str:
        """Submit order to IBKR."""
        contract = Stock(order.symbol, 'SMART', 'USD')

        if order.order_type == OrderType.MARKET:
            ib_order = MarketOrder(
                action='BUY' if order.side == OrderSide.BUY else 'SELL',
                totalQuantity=float(order.quantity),
            )
        elif order.order_type == OrderType.LIMIT:
            ib_order = LimitOrder(
                action='BUY' if order.side == OrderSide.BUY else 'SELL',
                totalQuantity=float(order.quantity),
                lmtPrice=float(order.limit_price),
            )

        trade = self._ib.placeOrder(contract, ib_order)
        self._order_map[trade.order.orderId] = order.id
        return str(trade.order.orderId)

    async def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel order in IBKR."""
        # Find trade by orderId and cancel
        ...

    async def get_positions(self) -> list[Position]:
        """Get positions from IBKR."""
        ib_positions = self._ib.positions()
        # Convert to our Position type
        ...

    def _on_order_status(self, trade: Trade) -> None:
        """Handle order status updates."""
        # Update order status in our system
        ...

    def _on_execution(self, trade: Trade, fill: IBFill) -> None:
        """Handle execution/fill events."""
        order_id = self._order_map.get(trade.order.orderId)
        if order_id and self._fill_callback:
            our_fill = Fill(
                order_id=order_id,
                strategy_id=...,  # Need to track this
                symbol=trade.contract.symbol,
                side=OrderSide.BUY if trade.order.action == 'BUY' else OrderSide.SELL,
                quantity=Decimal(str(fill.execution.shares)),
                price=Decimal(str(fill.execution.price)),
                commission=Decimal(str(fill.commissionReport.commission)) if fill.commissionReport else Decimal("0"),
            )
            asyncio.create_task(self._fill_callback(our_fill))
```

### 2. Risk Manager (oms/risk.py)

```python
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from axtrade.oms import Order, Position


@dataclass
class RiskLimits:
    """Risk limit configuration."""
    max_position_size: int = 1000              # Max shares per position
    max_position_value: Decimal = Decimal("50000")  # Max $ per position
    max_order_size: int = 500                  # Max shares per order
    max_daily_loss: Decimal = Decimal("1000")  # Max daily loss before halt
    max_open_orders: int = 10                  # Max concurrent open orders


@dataclass
class RiskCheckResult:
    """Result of a risk check."""
    approved: bool
    reason: Optional[str] = None


class RiskManager:
    """Pre-trade risk checks."""

    def __init__(self, limits: RiskLimits):
        self.limits = limits
        self._daily_pnl = Decimal("0")
        self._open_order_count = 0

    def check_order(
        self,
        order: Order,
        current_position: Optional[Position],
        current_price: Decimal,
    ) -> RiskCheckResult:
        """Run all risk checks on an order."""

        # Check order size
        if order.quantity > self.limits.max_order_size:
            return RiskCheckResult(
                approved=False,
                reason=f"Order size {order.quantity} exceeds limit {self.limits.max_order_size}",
            )

        # Check position size after fill
        new_position_size = order.quantity
        if current_position:
            if order.side == OrderSide.BUY:
                new_position_size = current_position.quantity + order.quantity
            else:
                new_position_size = current_position.quantity - order.quantity

        if new_position_size > self.limits.max_position_size:
            return RiskCheckResult(
                approved=False,
                reason=f"Position would exceed {self.limits.max_position_size} shares",
            )

        # Check position value
        position_value = new_position_size * current_price
        if position_value > self.limits.max_position_value:
            return RiskCheckResult(
                approved=False,
                reason=f"Position value ${position_value} exceeds limit ${self.limits.max_position_value}",
            )

        # Check daily loss limit
        if self._daily_pnl < -self.limits.max_daily_loss:
            return RiskCheckResult(
                approved=False,
                reason=f"Daily loss limit reached: ${self._daily_pnl}",
            )

        # Check open orders
        if self._open_order_count >= self.limits.max_open_orders:
            return RiskCheckResult(
                approved=False,
                reason=f"Max open orders ({self.limits.max_open_orders}) reached",
            )

        return RiskCheckResult(approved=True)

    def record_fill(self, pnl: Optional[Decimal]) -> None:
        """Record P&L from a fill."""
        if pnl:
            self._daily_pnl += pnl

    def order_submitted(self) -> None:
        """Track open order count."""
        self._open_order_count += 1

    def order_completed(self) -> None:
        """Track open order count."""
        self._open_order_count = max(0, self._open_order_count - 1)

    def reset_daily(self) -> None:
        """Reset daily counters (call at market open)."""
        self._daily_pnl = Decimal("0")
```

### 3. Config Extensions (common/config.py)

```python
@dataclass
class RiskConfig:
    """Risk management configuration."""
    max_position_size: int = 1000
    max_position_value: float = 50000.0
    max_order_size: int = 500
    max_daily_loss: float = 1000.0
    max_open_orders: int = 10


@dataclass
class OMSConfig:
    """Order management configuration."""
    paper_mode: bool = True
    slippage_bps: int = 10
    risk: RiskConfig = field(default_factory=RiskConfig)
```

### 4. OrderManager Refactor (oms/manager.py)

```python
class OrderManager:
    """Manages order lifecycle with broker integration."""

    def __init__(
        self,
        config: Config,
        db_pool: DatabasePool,
    ):
        self.config = config
        self._db_pool = db_pool
        self._order_repo: Optional[OrderRepository] = None
        self._position_repo: Optional[PositionRepository] = None
        self._broker: Optional[BrokerProtocol] = None
        self._risk_manager: Optional[RiskManager] = None
        self._last_prices: dict[str, Decimal] = {}

    async def connect(self) -> None:
        """Initialize repositories and broker."""
        self._order_repo = OrderRepository(self._db_pool)
        self._position_repo = PositionRepository(self._db_pool)

        # Initialize risk manager
        limits = RiskLimits(
            max_position_size=self.config.oms.risk.max_position_size,
            max_position_value=Decimal(str(self.config.oms.risk.max_position_value)),
            max_order_size=self.config.oms.risk.max_order_size,
            max_daily_loss=Decimal(str(self.config.oms.risk.max_daily_loss)),
            max_open_orders=self.config.oms.risk.max_open_orders,
        )
        self._risk_manager = RiskManager(limits)

        # Initialize broker
        if self.config.oms.paper_mode:
            self._broker = PaperBroker(slippage_bps=self.config.oms.slippage_bps)
        else:
            self._broker = IBKRBroker(self.config.ibkr)

        self._broker.set_fill_callback(self._on_fill)
        await self._broker.connect()

    async def disconnect(self) -> None:
        if self._broker:
            await self._broker.disconnect()

    async def submit_order(self, order: Order) -> UUID:
        """Submit order with risk checks."""
        # Get current position
        position = await self._position_repo.get(order.strategy_id, order.symbol)

        # Get current price
        price = self._last_prices.get(order.symbol, Decimal("0"))

        # Run risk checks
        result = self._risk_manager.check_order(order, position, price)
        if not result.approved:
            order.status = OrderStatus.REJECTED
            await self._order_repo.insert(order)
            self.logger.warning("Order rejected", reason=result.reason)
            raise OrderRejectedError(result.reason)

        # Submit to broker
        await self._order_repo.insert(order)
        broker_id = await self._broker.submit_order(order)

        order.status = OrderStatus.SUBMITTED
        await self._order_repo.update(order)
        self._risk_manager.order_submitted()

        return order.id

    async def _on_fill(self, fill: Fill) -> None:
        """Handle fill from broker."""
        # Update order
        order = await self._order_repo.get(fill.order_id)
        order.filled_quantity += fill.quantity
        if order.filled_quantity >= order.quantity:
            order.status = OrderStatus.FILLED
            self._risk_manager.order_completed()
        else:
            order.status = OrderStatus.PARTIAL
        order.avg_fill_price = fill.price  # Simplified; should be weighted avg
        await self._order_repo.update(order)

        # Insert fill
        await self._order_repo.insert_fill(fill)

        # Update position
        await self._update_position(fill)

    def update_price(self, symbol: str, price: Decimal) -> None:
        """Update price for risk checks and paper fills."""
        self._last_prices[symbol] = price
        if isinstance(self._broker, PaperBroker):
            self._broker.update_price(symbol, price)
```

### 5. Config Updates (config/default.yaml)

```yaml
oms:
  paper_mode: true
  slippage_bps: 10
  risk:
    max_position_size: 1000
    max_position_value: 50000
    max_order_size: 500
    max_daily_loss: 1000
    max_open_orders: 10

ibkr:
  host: "127.0.0.1"
  port: 7497          # TWS paper: 7497, live: 7496. Gateway paper: 4002, live: 4001
  client_id: 1
```

## Implementation Order

1. **Config**: Add RiskConfig to OMSConfig, update default.yaml
2. **Risk Manager**: Create oms/risk.py with RiskManager and RiskLimits
3. **Broker Protocol**: Create oms/broker.py with BrokerProtocol, PaperBroker
4. **IBKR Broker**: Add IBKRBroker to broker.py
5. **OrderManager Refactor**: Update manager.py to use broker protocol and risk manager
6. **Tests**: Unit tests for risk manager and broker protocol
7. **Integration**: Test with IBKR paper trading

## Test Cases

### RiskManager Tests
- Order size exceeds limit -> rejected
- Position size would exceed limit -> rejected
- Position value would exceed limit -> rejected
- Daily loss limit reached -> rejected
- Max open orders reached -> rejected
- Valid order -> approved
- Daily reset clears counters

### PaperBroker Tests
- Submit order generates fill
- Slippage applied correctly
- Fill callback invoked

### IBKRBroker Tests (integration)
- Connect to TWS/Gateway
- Submit market order
- Submit limit order
- Cancel order
- Receive fill callback
- Get positions

## Verification Steps

1. Test risk manager:
   ```bash
   pytest tests/unit/test_risk.py -v
   ```

2. Test with paper mode:
   ```bash
   make infra
   make run & make run-aggregator & make run-strategy
   # Verify orders fill in paper mode
   ```

3. Test with IBKR paper trading:
   - Start TWS/Gateway in paper mode
   - Set `oms.paper_mode: false` in config
   - Run strategy and verify orders appear in TWS

## Key Design Decisions

1. **Broker Protocol**: Abstract broker interface allows swapping paper/live easily
2. **Risk Manager**: Runs pre-trade checks before order submission
3. **Async Fills**: IBKRBroker uses callbacks for fill notifications
4. **Price Tracking**: OrderManager tracks last prices for risk checks
5. **Graceful Degradation**: If IBKR disconnects, orders are rejected rather than queued
