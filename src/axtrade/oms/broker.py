"""Broker implementations for order execution."""

import asyncio
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from axtrade.common import CommissionConfig, IBKRConfig, get_logger

from .types import Fill, Order, OrderSide, OrderStatus, OrderType, Position

if TYPE_CHECKING:
    from ib_insync import IB, Trade


def calculate_commission(
    quantity: Decimal, price: Decimal, config: CommissionConfig
) -> Decimal:
    """Calculate commission using IBKR Pro Fixed rate model.

    Args:
        quantity: Number of shares
        price: Execution price per share
        config: Commission configuration

    Returns:
        Commission amount (per_share * qty, clamped to [minimum, max_pct% of trade value])
    """
    comm = config.per_share * quantity
    max_comm = price * quantity * config.max_pct / Decimal("100")
    return max(min(comm, max_comm), config.minimum)


class InsufficientCashError(Exception):
    """Raised by PaperBroker when a buy would overdraw the cash balance.

    Caught upstream by OrderManager and translated to OrderRejectedError
    so the strategy sees a clean rejection rather than a crash.
    """


class VolumeCapExceededError(Exception):
    """Raised by PaperBroker when an order exceeds the volume-participation cap.

    Caught upstream by OrderManager and translated to OrderRejectedError
    so the strategy sees a clean rejection rather than a crash.
    """


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
    def update_price(self, symbol: str, price: Decimal, volume: Optional[Decimal] = None) -> None:
        """Update current price for a symbol.

        Args:
            symbol: Trading symbol
            price: Current price
            volume: Current bar volume, if known
        """
        ...

    @abstractmethod
    def set_terminal_callback(
        self, callback: Callable[[UUID, OrderStatus], Awaitable[None]]
    ) -> None:
        """Set callback for broker-side terminal transitions without a fill.

        Invoked when an order reaches a terminal state broker-side (e.g.
        cancelled or rejected) WITHOUT ever producing a fill. Fills still
        flow through the fill callback; this covers the "died with no
        fill" case so OrderManager can release the open-order counter and
        stamp CANCELLED/REJECTED instead of leaving the order stuck.

        Args:
            callback: Async function called with (our order ID, terminal status)
        """
        ...


class PaperBroker(BrokerProtocol):
    """Paper trading broker with simulated fills."""

    def __init__(
        self,
        slippage_bps: int = 10,
        commission_config: CommissionConfig | None = None,
        initial_cash: Decimal | None = None,
        max_volume_participation: float = 0.0,
    ):
        """Initialize paper broker.

        Args:
            slippage_bps: Slippage in basis points (1 bp = 0.01%)
            commission_config: Commission model configuration
            initial_cash: Starting cash balance. When set, buys are rejected
                if they would overdraw. None = unlimited (legacy live-mode
                behavior; real brokers enforce cash on their side).
            max_volume_participation: When > 0, orders larger than this
                fraction of the symbol's last known bar volume are rejected.
                0 = disabled (legacy behavior). Audit C3.
        """
        self.slippage_bps = slippage_bps
        self.commission_config = commission_config or CommissionConfig()
        self.max_volume_participation = max_volume_participation
        self.logger = get_logger("paper_broker")

        self._last_prices: dict[str, Decimal] = {}
        self._last_volumes: dict[str, Decimal] = {}
        self._positions: dict[str, Position] = {}
        self._fill_callback: Optional[Callable[[Fill], Awaitable[None]]] = None
        self._terminal_callback: Optional[Callable[[UUID, OrderStatus], Awaitable[None]]] = None
        self._connected = False
        # Simulated clock: when set, fills are timestamped with this rather than
        # wall-clock. Fulltest advances it per bar so analytics see sim time.
        self._current_time: Optional[datetime] = None
        self._cash: Optional[Decimal] = initial_cash

    @property
    def cash(self) -> Optional[Decimal]:
        """Current cash balance, or None if unlimited."""
        return self._cash

    def set_current_time(self, ts: datetime) -> None:
        """Override the broker's notion of 'now' for fill timestamps.

        In live trading this should not be called (fills carry wall clock).
        In fulltest the strategy runner sets this on every bar so fills line
        up with the simulated period.
        """
        self._current_time = ts

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
            if order.limit_price:
                price = order.limit_price
            else:
                raise RuntimeError(
                    f"No price available for {order.symbol} and no limit price set"
                )

        # Volume-participation cap (paper-only, when configured). Rejects
        # orders larger than a fraction of the symbol's last known bar
        # volume, for both buys and sells. Unknown volume (never reported
        # for this symbol) skips the check permissively. Audit C3.
        if self.max_volume_participation > 0:
            last_volume = self._last_volumes.get(order.symbol)
            if last_volume is not None:
                cap = last_volume * Decimal(str(self.max_volume_participation))
                if order.quantity > cap:
                    raise VolumeCapExceededError(
                        f"{order.symbol} order quantity {order.quantity} exceeds "
                        f"volume cap {cap} ({self.max_volume_participation:.2%} of "
                        f"last bar volume {last_volume})"
                    )

        # Apply slippage
        slippage_mult = Decimal(str(1 + (self.slippage_bps / 10000)))
        if order.side == OrderSide.BUY:
            exec_price = price * slippage_mult
        else:
            exec_price = price / slippage_mult
        exec_price = exec_price.quantize(Decimal("0.01"))

        commission = calculate_commission(
            order.quantity, exec_price, self.commission_config
        )

        # Cash check (paper-only, when initial_cash was set). On a buy: reject
        # if cash can't cover cost + commission. On a sell: cash will go up.
        if self._cash is not None and order.side == OrderSide.BUY:
            required = exec_price * order.quantity + commission
            if self._cash < required:
                raise InsufficientCashError(
                    f"Need ${required:.2f} for {order.quantity}@{exec_price} {order.symbol} "
                    f"(commission ${commission:.2f}); have ${self._cash:.2f}"
                )

        # Create fill (simulated clock if set, else wall-clock default).
        fill_kwargs: dict = {
            "order_id": order.id,
            "strategy_id": order.strategy_id,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "price": exec_price,
            "commission": commission,
        }
        if self._current_time is not None:
            fill_kwargs["filled_at"] = self._current_time
        fill = Fill(**fill_kwargs)

        # Update cash. Buy reduces by cost+commission; sell adds proceeds net
        # of commission. Only when cash tracking is enabled.
        if self._cash is not None:
            if order.side == OrderSide.BUY:
                self._cash -= exec_price * order.quantity + commission
            else:
                self._cash += exec_price * order.quantity - commission

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

    def set_terminal_callback(
        self, callback: Callable[[UUID, OrderStatus], Awaitable[None]]
    ) -> None:
        """Set callback for broker-side terminal transitions without a fill.

        PaperBroker resolves every order synchronously inside submit_order
        (immediate FILLED, or an exception translated by OrderManager) and
        never holds a resting order — cancel_order above always no-ops for
        exactly that reason. There is no broker-side "cancelled/rejected
        with no fill" transition for this callback to report, so it is
        stored for protocol conformance but never invoked.

        Args:
            callback: Async function called with (order ID, terminal status)
        """
        self._terminal_callback = callback

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

    def update_price(self, symbol: str, price: Decimal, volume: Optional[Decimal] = None) -> None:
        """Update current price for a symbol.

        Args:
            symbol: Trading symbol
            price: Current price
            volume: Current bar volume, if known. Used by the volume-
                participation cap; unknown symbols skip that check.
        """
        self._last_prices[symbol] = price
        if volume is not None:
            self._last_volumes[symbol] = volume

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

    # IBKR distinguishes paper vs live ONLY by port: TWS 7497 paper / 7496
    # live, IB Gateway 4002 paper / 4001 live. Live (real-money) trading is
    # out of scope until a strategy earns it (docs/ibkr-connection-design.md D3).
    _LIVE_PORTS = frozenset({7496, 4001})

    def __init__(self, config: IBKRConfig, allow_live: bool = False):
        """Initialize IBKR broker.

        Args:
            config: IBKR connection configuration
            allow_live: When False (default), connect() refuses live ports
                (7496/4001). Set from oms.ibkr_allow_live.
        """
        self.config = config
        self.allow_live = allow_live
        self.logger = get_logger("ibkr_broker")

        self._ib: Optional["IB"] = None
        self._fill_callback: Optional[Callable[[Fill], Awaitable[None]]] = None
        self._terminal_callback: Optional[Callable[[UUID, OrderStatus], Awaitable[None]]] = None
        self._order_map: dict[int, tuple[UUID, str]] = {}  # IBKR orderId -> (our order ID, strategy_id)
        self._last_prices: dict[str, Decimal] = {}
        self._pending_callbacks: list[asyncio.Task] = []
        # Terminal IBKR order states reported without a fill. Live/Inactive
        # states we don't treat as terminal (e.g. "Submitted", "PreSubmitted")
        # are left alone.
        self._terminal_no_fill_statuses = frozenset({"Cancelled", "ApiCancelled", "Inactive"})

    async def connect(self) -> None:
        """Connect to TWS/Gateway."""
        if self.config.port in self._LIVE_PORTS and not self.allow_live:
            raise RuntimeError(
                f"Refusing to connect IBKRBroker to live port {self.config.port} "
                "(7496 TWS / 4001 IB Gateway); set oms.ibkr_allow_live: true to "
                "enable live (real-money) trading."
            )

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

    def set_terminal_callback(
        self, callback: Callable[[UUID, OrderStatus], Awaitable[None]]
    ) -> None:
        """Set callback for broker-side terminal transitions without a fill.

        Args:
            callback: Async function called with (our order ID, terminal status)
        """
        self._terminal_callback = callback

    def update_price(self, symbol: str, price: Decimal, volume: Optional[Decimal] = None) -> None:
        """Update current price for a symbol.

        Args:
            symbol: Trading symbol
            price: Current price
            volume: Current bar volume, if known. Unused by IBKRBroker — the
                real broker enforces its own liquidity/participation limits.
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

        if status not in self._terminal_no_fill_statuses:
            return

        order_info = self._order_map.get(trade.order.orderId)
        if not order_info:
            self.logger.warning(
                "Received terminal status for unknown order",
                ibkr_order_id=trade.order.orderId,
                status=status,
            )
            return

        order_id, _strategy_id = order_info

        self.logger.info(
            "Order reached terminal state without fill",
            ibkr_order_id=trade.order.orderId,
            order_id=str(order_id),
            status=status,
        )

        # Invoke callback asynchronously, same detached-task pattern as
        # _on_execution below (this is a sync ib_insync event handler).
        if self._terminal_callback:
            task = asyncio.create_task(
                self._terminal_callback(order_id, OrderStatus.CANCELLED)
            )
            self._pending_callbacks.append(task)
            task.add_done_callback(lambda t: self._pending_callbacks.remove(t))

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
