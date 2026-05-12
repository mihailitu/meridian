"""Order management and execution."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Callable, Optional
from uuid import UUID

import redis.asyncio as redis

from axtrade.common.config import Config
from axtrade.common.db import DatabasePool
from axtrade.common.logging import get_logger

from .broker import BrokerProtocol, IBKRBroker, InsufficientCashError, PaperBroker
from .repository import OrderRepository, PositionRepository
from .risk import RiskCheckResult, RiskLimits, RiskManager
from .types import Fill, Order, OrderSide, OrderStatus, Position


class OrderRejectedError(Exception):
    """Raised when an order is rejected by risk checks."""

    pass


class OrderManager:
    """Manages order submission and execution.

    Uses BrokerProtocol for execution (paper or live) and RiskManager
    for pre-trade validation.
    """

    def __init__(self, config: Config, pool: DatabasePool):
        """Initialize order manager.

        Args:
            config: Application configuration
            pool: Database connection pool
        """
        self.config = config
        self._pool = pool
        self.logger = get_logger("oms")

        self._order_repo: Optional[OrderRepository] = None
        self._position_repo: Optional[PositionRepository] = None
        self._redis: Optional[redis.Redis] = None
        self._broker: Optional[BrokerProtocol] = None
        self._risk_manager: Optional[RiskManager] = None

        # Callbacks for fill notifications
        self._fill_callbacks: list[Callable[[Fill], None]] = []

        # Price cache for risk checks
        self._last_prices: dict[str, Decimal] = {}

    async def connect(self) -> None:
        """Initialize repositories, broker, and connections."""
        self._order_repo = OrderRepository(self._pool)
        self._position_repo = PositionRepository(self._pool)

        self._redis = redis.Redis(
            host=self.config.redis.host,
            port=self.config.redis.port,
            db=self.config.redis.db,
            decode_responses=True,
        )
        await self._redis.ping()

        # Initialize risk manager
        risk_config = self.config.oms.risk
        limits = RiskLimits(
            max_position_size=risk_config.max_position_size,
            max_position_value=Decimal(str(risk_config.max_position_value)),
            max_order_size=risk_config.max_order_size,
            max_daily_loss=Decimal(str(risk_config.max_daily_loss)),
            max_open_orders=risk_config.max_open_orders,
        )
        self._risk_manager = RiskManager(limits)

        # Initialize broker
        if self.config.oms.paper_mode:
            self._broker = PaperBroker(
                slippage_bps=self.config.oms.slippage_bps,
                commission_config=self.config.oms.commission,
                initial_cash=self.config.oms.initial_capital,
            )
        else:
            self._broker = IBKRBroker(self.config.gateway.ibkr)

        self._broker.set_fill_callback(self._on_broker_fill)
        await self._broker.connect()

        self.logger.info(
            "OrderManager initialized",
            paper_mode=self.config.oms.paper_mode,
            max_position_size=limits.max_position_size,
            max_daily_loss=str(limits.max_daily_loss),
        )

    async def disconnect(self) -> None:
        """Close connections."""
        if self._broker:
            await self._broker.disconnect()
            self._broker = None

        if self._redis:
            await self._redis.aclose()
            self._redis = None

    def on_fill(self, callback: Callable[[Fill], None]) -> None:
        """Register a callback for fill notifications.

        Args:
            callback: Function to call when fills occur
        """
        self._fill_callbacks.append(callback)

    def update_price(self, symbol: str, price: float) -> None:
        """Update cached price for risk checks and paper trading.

        Args:
            symbol: Trading symbol
            price: Current price
        """
        decimal_price = Decimal(str(price))
        self._last_prices[symbol] = decimal_price
        if self._broker:
            self._broker.update_price(symbol, decimal_price)

    def set_current_time(self, ts) -> None:
        """Forward simulated-time updates to the broker (PaperBroker only).

        No-op if the broker doesn't expose set_current_time. Lets fulltest
        timestamp fills with bar time so analytics see the simulated period.
        """
        if self._broker and hasattr(self._broker, "set_current_time"):
            self._broker.set_current_time(ts)

    async def submit_order(self, order: Order) -> UUID:
        """Submit an order for execution.

        Args:
            order: Order to submit

        Returns:
            Order ID

        Raises:
            OrderRejectedError: If order fails risk checks
            RuntimeError: If not connected
        """
        if not self._order_repo or not self._broker or not self._risk_manager:
            raise RuntimeError("OrderManager not connected")

        # Get current position for risk check
        position = await self._position_repo.get(order.strategy_id, order.symbol)

        # Get current price for risk check
        price = self._last_prices.get(order.symbol, Decimal("0"))

        # Run risk checks
        result = self._risk_manager.check_order(order, position, price)
        if not result.approved:
            order.status = OrderStatus.REJECTED
            await self._order_repo.insert(order)
            self.logger.debug(
                "Order rejected by risk manager",
                order_id=str(order.id),
                reason=result.reason,
            )
            raise OrderRejectedError(result.reason)

        # Global max positions guard
        if order.side == OrderSide.BUY:
            is_new_position = position is None or position.quantity == 0
            if is_new_position:
                all_open = await self.get_open_positions()
                max_pos = self.config.oms.max_positions
                if len(all_open) >= max_pos:
                    order.status = OrderStatus.REJECTED
                    await self._order_repo.insert(order)
                    reason = f"Max positions ({max_pos}) reached"
                    self.logger.debug(
                        "Order rejected: max positions",
                        order_id=str(order.id),
                        open_positions=len(all_open),
                        max_positions=max_pos,
                    )
                    raise OrderRejectedError(reason)

        # Persist the order
        await self._order_repo.insert(order)

        self.logger.info(
            "Order submitted",
            order_id=str(order.id),
            strategy=order.strategy_id,
            symbol=order.symbol,
            side=order.side.value,
            quantity=str(order.quantity),
            order_type=order.order_type.value,
        )

        # Submit to broker
        # Track open order BEFORE broker submission since PaperBroker
        # fills synchronously (fill callback fires inside submit_order),
        # which calls order_completed() to decrement the counter.
        self._risk_manager.order_submitted()
        try:
            broker_order_id = await self._broker.submit_order(order)
            order.status = OrderStatus.SUBMITTED
            await self._order_repo.update(order)

            self.logger.debug(
                "Order sent to broker",
                order_id=str(order.id),
                broker_order_id=broker_order_id,
            )
        except InsufficientCashError as e:
            # Paper-mode cash check tripped — clean rejection, not a crash.
            self._risk_manager.order_completed()
            order.status = OrderStatus.REJECTED
            await self._order_repo.update(order)
            raise OrderRejectedError(str(e)) from e
        except Exception as e:
            self._risk_manager.order_completed()
            order.status = OrderStatus.REJECTED
            await self._order_repo.update(order)
            self.logger.error("Broker submission failed", error=str(e))
            raise

        return order.id

    async def _on_broker_fill(self, fill: Fill) -> None:
        """Handle fill callback from broker.

        Args:
            fill: Fill from broker
        """
        if not self._order_repo or not self._position_repo or not self._risk_manager:
            return

        # Get and update order
        order = await self._order_repo.get(fill.order_id)
        if order:
            order.filled_quantity += fill.quantity
            if order.filled_quantity >= order.quantity:
                order.status = OrderStatus.FILLED
                self._risk_manager.order_completed()
            else:
                order.status = OrderStatus.PARTIAL

            # Update average fill price (weighted average for partial fills)
            if order.avg_fill_price:
                prev_value = order.avg_fill_price * (order.filled_quantity - fill.quantity)
                new_value = fill.price * fill.quantity
                order.avg_fill_price = (prev_value + new_value) / order.filled_quantity
            else:
                order.avg_fill_price = fill.price

            await self._order_repo.update(order)

        # Record fill
        await self._order_repo.insert_fill(fill)

        # Update position
        await self._update_position(fill)

        # Publish fill to Redis
        await self._publish_fill(fill)

        # Notify callbacks
        for callback in self._fill_callbacks:
            try:
                callback(fill)
            except Exception as e:
                self.logger.error("Fill callback error", error=str(e))

        self.logger.info(
            "Fill processed",
            order_id=str(fill.order_id),
            symbol=fill.symbol,
            side=fill.side.value,
            quantity=str(fill.quantity),
            price=str(fill.price),
        )

    async def _update_position(self, fill: Fill) -> None:
        """Update position based on a fill.

        Args:
            fill: Fill to process
        """
        if not self._position_repo or not self._risk_manager:
            return

        existing = await self._position_repo.get(fill.strategy_id, fill.symbol)
        pnl: Optional[Decimal] = None

        # A closed row (quantity==0 or closed_at set) should be treated as no
        # open position — the next fill starts a fresh position era. Without
        # this, re-entries pyramid onto the stale row and closed_at never
        # clears, leaving the strategy convinced it has no position.
        is_open = existing is not None and existing.closed_at is None and existing.quantity > 0

        if not is_open:
            # New position (or re-opening after a prior close). Carry forward
            # realized_pnl so the row reflects cumulative P&L for this
            # strategy+symbol; the fills table remains source of truth.
            prior_realized = existing.realized_pnl if existing is not None else Decimal("0")
            position = Position(
                strategy_id=fill.strategy_id,
                symbol=fill.symbol,
                side="long" if fill.side == OrderSide.BUY else "short",
                quantity=fill.quantity,
                avg_entry_price=fill.price,
                current_price=fill.price,
                unrealized_pnl=Decimal("0"),
                realized_pnl=prior_realized,
                opened_at=fill.filled_at,
                closed_at=None,
            )
        else:
            position = existing  # type: ignore[assignment]
            if fill.side == OrderSide.BUY:
                if position.side == "long":
                    # Adding to long position - calculate new average
                    total_cost = position.quantity * position.avg_entry_price + fill.quantity * fill.price
                    new_qty = position.quantity + fill.quantity
                    position.avg_entry_price = (total_cost / new_qty).quantize(Decimal("0.000001"))
                    position.quantity = new_qty
                else:
                    # Closing/reducing short - calculate P&L
                    close_qty = min(fill.quantity, position.quantity)
                    pnl = (position.avg_entry_price - fill.price) * close_qty
                    position.quantity = position.quantity - fill.quantity
                    if position.quantity < 0:
                        # Flipped to long
                        position.side = "long"
                        position.quantity = abs(position.quantity)
                        position.avg_entry_price = fill.price
            else:
                if position.side == "short":
                    # Adding to short position
                    total_cost = position.quantity * position.avg_entry_price + fill.quantity * fill.price
                    new_qty = position.quantity + fill.quantity
                    position.avg_entry_price = (total_cost / new_qty).quantize(Decimal("0.000001"))
                    position.quantity = new_qty
                else:
                    # Closing/reducing long - calculate P&L
                    close_qty = min(fill.quantity, position.quantity)
                    pnl = (fill.price - position.avg_entry_price) * close_qty
                    position.quantity = position.quantity - fill.quantity
                    if position.quantity < 0:
                        # Flipped to short
                        position.side = "short"
                        position.quantity = abs(position.quantity)
                        position.avg_entry_price = fill.price

        # Track P&L in risk manager
        if pnl is not None:
            self._risk_manager.record_pnl(pnl)
            position.realized_pnl += pnl

        # Update current price and unrealized P&L
        position.current_price = fill.price
        if position.quantity > 0:
            position.unrealized_pnl = position.calculate_unrealized_pnl(fill.price)
        else:
            position.unrealized_pnl = Decimal("0")
            position.closed_at = datetime.now(UTC)

        await self._position_repo.upsert(position)

    async def _publish_fill(self, fill: Fill) -> None:
        """Publish fill to Redis stream.

        Args:
            fill: Fill to publish
        """
        if not self._redis:
            return

        stream_key = "stream:fills"
        await self._redis.xadd(stream_key, fill.to_dict())

    async def get_position(self, strategy_id: str, symbol: str) -> Optional[Position]:
        """Get a position.

        Args:
            strategy_id: Strategy identifier
            symbol: Trading symbol

        Returns:
            Position if found, None otherwise
        """
        if not self._position_repo:
            return None
        return await self._position_repo.get(strategy_id, symbol)

    async def get_open_positions(self, strategy_id: Optional[str] = None) -> list[Position]:
        """Get all open positions.

        Args:
            strategy_id: Optional filter by strategy

        Returns:
            List of open positions
        """
        if not self._position_repo:
            return []
        return await self._position_repo.get_open_positions(strategy_id)

    @property
    def risk_manager(self) -> Optional[RiskManager]:
        """Get the risk manager."""
        return self._risk_manager
