"""Broker implementations for order execution."""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from axtrade.common import IBKRConfig, get_logger

from .types import Fill, Order, OrderSide, OrderStatus, OrderType, Position

if TYPE_CHECKING:
    from ib_insync import IB, Trade


class BrokerProtocol(ABC):
    """Abstract base class for order execution brokers."""

    @abstractmethod
    async def connect(self) -> None:
        """Connect to broker."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from broker."""
        ...

    @abstractmethod
    async def submit_order(self, order: Order) -> str:
        """Submit order and return broker order ID.

        Args:
            order: Order to submit

        Returns:
            Broker-assigned order ID
        """
        ...

    @abstractmethod
    async def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel an order.

        Args:
            broker_order_id: Broker-assigned order ID

        Returns:
            True if cancellation was successful
        """
        ...

    @abstractmethod
    async def get_positions(self) -> list[Position]:
        """Get current positions from broker.

        Returns:
            List of current positions
        """
        ...

    @abstractmethod
    def set_fill_callback(
        self, callback: Callable[[Fill], Awaitable[None]]
    ) -> None:
        """Set callback for fill notifications.

        Args:
            callback: Async function to call when fills occur
        """
        ...

    @abstractmethod
    def update_price(self, symbol: str, price: Decimal) -> None:
        """Update current price for a symbol.

        Args:
            symbol: Trading symbol
            price: Current price
        """
        ...


class PaperBroker(BrokerProtocol):
    """Paper trading broker with simulated fills."""

    def __init__(self, slippage_bps: int = 10):
        """Initialize paper broker.

        Args:
            slippage_bps: Slippage in basis points (1 bp = 0.01%)
        """
        self.slippage_bps = slippage_bps
        self.logger = get_logger("paper_broker")

        self._last_prices: dict[str, Decimal] = {}
        self._positions: dict[str, Position] = {}
        self._fill_callback: Optional[Callable[[Fill], Awaitable[None]]] = None
        self._connected = False

    async def connect(self) -> None:
        """Connect to paper broker (no-op)."""
        self._connected = True
        self.logger.info("Paper broker connected")

    async def disconnect(self) -> None:
        """Disconnect from paper broker (no-op)."""
        self._connected = False
        self.logger.info("Paper broker disconnected")

    async def submit_order(self, order: Order) -> str:
        """Submit order with immediate simulated fill.

        Args:
            order: Order to submit

        Returns:
            Order ID as string
        """
        if not self._connected:
            raise RuntimeError("Broker not connected")

        # Get current price
        price = self._last_prices.get(order.symbol)
        if price is None:
            self.logger.warning(
                "No price available for symbol, using limit price or rejecting",
                symbol=order.symbol,
            )
            if order.limit_price:
                price = order.limit_price
            else:
                order.status = OrderStatus.REJECTED
                return str(order.id)

        # Apply slippage
        slippage_mult = Decimal(str(1 + (self.slippage_bps / 10000)))
        if order.side == OrderSide.BUY:
            exec_price = price * slippage_mult
        else:
            exec_price = price / slippage_mult
        exec_price = exec_price.quantize(Decimal("0.01"))

        # Create fill
        fill = Fill(
            order_id=order.id,
            strategy_id=order.strategy_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=exec_price,
            commission=Decimal("1.00"),
        )

        # Update order status
        order.status = OrderStatus.FILLED
        order.filled_quantity = order.quantity
        order.avg_fill_price = exec_price

        # Update internal position tracking
        self._update_position(fill)

        # Notify via callback
        if self._fill_callback:
            await self._fill_callback(fill)

        self.logger.info(
            "Paper fill executed",
            symbol=order.symbol,
            side=order.side.value,
            quantity=str(order.quantity),
            price=str(exec_price),
        )

        return str(order.id)

    async def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel order (paper orders fill immediately, so nothing to cancel).

        Args:
            broker_order_id: Order ID

        Returns:
            False since paper orders fill immediately
        """
        self.logger.info("Cancel requested but paper orders fill immediately")
        return False

    def get_position(self, symbol: str) -> Optional[Position]:
        """Get position for a specific symbol.

        Args:
            symbol: Trading symbol

        Returns:
            Position if exists, None otherwise
        """
        return self._positions.get(symbol)

    async def get_positions(self) -> list[Position]:
        """Get current paper positions.

        Returns:
            List of current positions
        """
        return list(self._positions.values())

    def set_fill_callback(
        self, callback: Callable[[Fill], Awaitable[None]]
    ) -> None:
        """Set callback for fill notifications.

        Args:
            callback: Async function to call when fills occur
        """
        self._fill_callback = callback

    def update_price(self, symbol: str, price: Decimal) -> None:
        """Update current price for a symbol.

        Args:
            symbol: Trading symbol
            price: Current price
        """
        self._last_prices[symbol] = price

        # Update position mark-to-market
        if symbol in self._positions:
            pos = self._positions[symbol]
            pos.current_price = price
            pos.unrealized_pnl = pos.calculate_unrealized_pnl(price)

    def _update_position(self, fill: Fill) -> None:
        """Update internal position tracking after fill.

        Args:
            fill: Fill that occurred
        """
        symbol = fill.symbol
        current_pos = self._positions.get(symbol)

        if fill.side == OrderSide.BUY:
            if current_pos is None:
                # New long position
                self._positions[symbol] = Position(
                    strategy_id=fill.strategy_id,
                    symbol=symbol,
                    side="long",
                    quantity=fill.quantity,
                    avg_entry_price=fill.price,
                    current_price=fill.price,
                )
            else:
                # Add to position
                total_qty = current_pos.quantity + fill.quantity
                total_cost = (
                    current_pos.avg_entry_price * current_pos.quantity
                    + fill.price * fill.quantity
                )
                current_pos.avg_entry_price = total_cost / total_qty
                current_pos.quantity = total_qty
        else:
            # SELL
            if current_pos is None:
                # New short position
                self._positions[symbol] = Position(
                    strategy_id=fill.strategy_id,
                    symbol=symbol,
                    side="short",
                    quantity=fill.quantity,
                    avg_entry_price=fill.price,
                    current_price=fill.price,
                )
            else:
                # Reduce position
                current_pos.quantity -= fill.quantity
                if current_pos.quantity <= 0:
                    del self._positions[symbol]

    @property
    def connected(self) -> bool:
        """Check if broker is connected."""
        return self._connected


class IBKRBroker(BrokerProtocol):
    """Interactive Brokers order execution via ib_insync."""

    def __init__(self, config: IBKRConfig):
        """Initialize IBKR broker.

        Args:
            config: IBKR connection configuration
        """
        self.config = config
        self.logger = get_logger("ibkr_broker")

        self._ib: Optional["IB"] = None
        self._fill_callback: Optional[Callable[[Fill], Awaitable[None]]] = None
        self._order_map: dict[int, tuple[UUID, str]] = {}  # IBKR orderId -> (our order ID, strategy_id)
        self._last_prices: dict[str, Decimal] = {}
        self._pending_callbacks: list[asyncio.Task] = []

    async def connect(self) -> None:
        """Connect to TWS/Gateway."""
        from ib_insync import IB

        self._ib = IB()
        await self._ib.connectAsync(
            host=self.config.host,
            port=self.config.port,
            clientId=self.config.client_id,
        )

        # Subscribe to order events
        self._ib.orderStatusEvent += self._on_order_status
        self._ib.execDetailsEvent += self._on_execution

        self.logger.info(
            "Connected to IBKR",
            host=self.config.host,
            port=self.config.port,
            client_id=self.config.client_id,
        )

    async def disconnect(self) -> None:
        """Disconnect from TWS/Gateway."""
        # Wait for pending callbacks
        if self._pending_callbacks:
            await asyncio.gather(*self._pending_callbacks, return_exceptions=True)
            self._pending_callbacks.clear()

        if self._ib:
            self._ib.orderStatusEvent -= self._on_order_status
            self._ib.execDetailsEvent -= self._on_execution
            self._ib.disconnect()
            self._ib = None

        self.logger.info("Disconnected from IBKR")

    async def submit_order(self, order: Order) -> str:
        """Submit order to IBKR.

        Args:
            order: Order to submit

        Returns:
            IBKR order ID as string
        """
        if not self._ib or not self._ib.isConnected():
            raise RuntimeError("Not connected to IBKR")

        from ib_insync import LimitOrder, MarketOrder, Stock

        # Create contract
        contract = Stock(order.symbol, "SMART", "USD")

        # Create order
        action = "BUY" if order.side == OrderSide.BUY else "SELL"
        quantity = float(order.quantity)

        if order.order_type == OrderType.MARKET:
            ib_order = MarketOrder(action=action, totalQuantity=quantity)
        elif order.order_type == OrderType.LIMIT:
            if order.limit_price is None:
                raise ValueError("Limit order requires limit_price")
            ib_order = LimitOrder(
                action=action,
                totalQuantity=quantity,
                lmtPrice=float(order.limit_price),
            )
        else:
            raise ValueError(f"Unsupported order type: {order.order_type}")

        # Submit order
        trade = self._ib.placeOrder(contract, ib_order)

        # Track order mapping
        self._order_map[trade.order.orderId] = (order.id, order.strategy_id)

        self.logger.info(
            "Order submitted to IBKR",
            symbol=order.symbol,
            side=action,
            quantity=quantity,
            order_type=order.order_type.value,
            ibkr_order_id=trade.order.orderId,
        )

        return str(trade.order.orderId)

    async def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel an order in IBKR.

        Args:
            broker_order_id: IBKR order ID

        Returns:
            True if cancellation was requested successfully
        """
        if not self._ib or not self._ib.isConnected():
            return False

        try:
            order_id = int(broker_order_id)
            # Find the trade with this order ID
            for trade in self._ib.openTrades():
                if trade.order.orderId == order_id:
                    self._ib.cancelOrder(trade.order)
                    self.logger.info("Cancel requested", ibkr_order_id=order_id)
                    return True
            return False
        except (ValueError, Exception) as e:
            self.logger.error("Failed to cancel order", error=str(e))
            return False

    async def get_positions(self) -> list[Position]:
        """Get current positions from IBKR.

        Returns:
            List of current positions
        """
        if not self._ib or not self._ib.isConnected():
            return []

        positions = []
        for ib_pos in self._ib.positions():
            if ib_pos.position != 0:
                side = "long" if ib_pos.position > 0 else "short"
                positions.append(
                    Position(
                        strategy_id="ibkr",  # IBKR positions aren't strategy-specific
                        symbol=ib_pos.contract.symbol,
                        side=side,
                        quantity=Decimal(str(abs(ib_pos.position))),
                        avg_entry_price=Decimal(str(ib_pos.avgCost)),
                    )
                )

        return positions

    def set_fill_callback(
        self, callback: Callable[[Fill], Awaitable[None]]
    ) -> None:
        """Set callback for fill notifications.

        Args:
            callback: Async function to call when fills occur
        """
        self._fill_callback = callback

    def update_price(self, symbol: str, price: Decimal) -> None:
        """Update current price for a symbol.

        Args:
            symbol: Trading symbol
            price: Current price
        """
        self._last_prices[symbol] = price

    def _on_order_status(self, trade: "Trade") -> None:
        """Handle order status updates from IBKR.

        Args:
            trade: IBKR trade object
        """
        status = trade.orderStatus.status
        self.logger.debug(
            "Order status update",
            ibkr_order_id=trade.order.orderId,
            status=status,
        )

    def _on_execution(self, trade: "Trade", fill: object) -> None:
        """Handle execution/fill events from IBKR.

        Args:
            trade: IBKR trade object
            fill: IBKR fill object
        """
        order_info = self._order_map.get(trade.order.orderId)
        if not order_info:
            self.logger.warning(
                "Received fill for unknown order",
                ibkr_order_id=trade.order.orderId,
            )
            return

        order_id, strategy_id = order_info

        # Extract commission from fill
        commission = Decimal("0")
        if hasattr(fill, "commissionReport") and fill.commissionReport:
            comm = fill.commissionReport.commission
            if comm is not None and comm > 0:
                commission = Decimal(str(comm))

        # Create our fill object
        our_fill = Fill(
            order_id=order_id,
            strategy_id=strategy_id,
            symbol=trade.contract.symbol,
            side=OrderSide.BUY if trade.order.action == "BUY" else OrderSide.SELL,
            quantity=Decimal(str(fill.execution.shares)),
            price=Decimal(str(fill.execution.price)),
            commission=commission,
        )

        self.logger.info(
            "Fill received from IBKR",
            symbol=our_fill.symbol,
            side=our_fill.side.value,
            quantity=str(our_fill.quantity),
            price=str(our_fill.price),
        )

        # Invoke callback asynchronously
        if self._fill_callback:
            task = asyncio.create_task(self._fill_callback(our_fill))
            self._pending_callbacks.append(task)
            task.add_done_callback(lambda t: self._pending_callbacks.remove(t))

    @property
    def connected(self) -> bool:
        """Check if broker is connected."""
        return self._ib is not None and self._ib.isConnected()
