"""Risk management for order validation."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from .types import Order, OrderSide, Position


@dataclass
class RiskLimits:
    """Risk limit configuration."""

    max_position_size: int = 1000  # Max shares per position
    max_position_value: Decimal = Decimal("50000")  # Max $ per position
    max_order_size: int = 500  # Max shares per order
    max_daily_loss: Decimal = Decimal("1000")  # Max daily loss before halt
    max_open_orders: int = 10  # Max concurrent open orders


@dataclass
class RiskCheckResult:
    """Result of a risk check."""

    approved: bool
    reason: Optional[str] = None


class RiskManager:
    """Pre-trade risk checks."""

    def __init__(self, limits: RiskLimits):
        """Initialize risk manager.

        Args:
            limits: Risk limit configuration
        """
        self.limits = limits
        self._daily_pnl = Decimal("0")
        self._open_order_count = 0

    def check_order(
        self,
        order: Order,
        current_position: Optional[Position],
        current_price: Decimal,
    ) -> RiskCheckResult:
        """Run all risk checks on an order.

        Args:
            order: Order to check
            current_position: Current position for the symbol, if any
            current_price: Current market price for the symbol

        Returns:
            RiskCheckResult with approval status and reason if rejected
        """
        # Reduce-only orders (sells that shrink or close an existing long
        # without flipping short) bypass every pre-trade cap: the caps exist
        # to limit NEW exposure, and rejecting an exit increases risk instead
        # of capping it. Before this, a tripped shared daily-loss limit
        # blocked position closes for the rest of the day — in the recorded
        # post-data-fixes run one such rejection froze a pairs position for
        # six months (audit P1-12).
        if (
            order.side == OrderSide.SELL
            and current_position is not None
            and current_position.quantity > 0
            and order.quantity <= current_position.quantity
        ):
            return RiskCheckResult(approved=True)

        # Check order size
        if order.quantity > self.limits.max_order_size:
            return RiskCheckResult(
                approved=False,
                reason=f"Order size {order.quantity} exceeds limit {self.limits.max_order_size}",
            )

        # Calculate position size after fill
        current_qty = current_position.quantity if current_position else Decimal("0")

        if order.side == OrderSide.BUY:
            new_position_size = current_qty + order.quantity
        else:
            # For sells, we're reducing position
            new_position_size = current_qty - order.quantity
            if new_position_size < 0:
                # Short selling - use absolute value
                new_position_size = abs(new_position_size)

        # Check position size limit
        if new_position_size > self.limits.max_position_size:
            return RiskCheckResult(
                approved=False,
                reason=f"Position would exceed {self.limits.max_position_size} shares",
            )

        # Check position value limit
        if current_price > 0:
            position_value = new_position_size * current_price
            if position_value > self.limits.max_position_value:
                return RiskCheckResult(
                    approved=False,
                    reason=f"Position value ${position_value:.2f} exceeds limit ${self.limits.max_position_value:.2f}",
                )

        # Check daily loss limit
        if self._daily_pnl < -self.limits.max_daily_loss:
            return RiskCheckResult(
                approved=False,
                reason=f"Daily loss limit reached: ${self._daily_pnl:.2f}",
            )

        # Check open orders limit
        if self._open_order_count >= self.limits.max_open_orders:
            return RiskCheckResult(
                approved=False,
                reason=f"Max open orders ({self.limits.max_open_orders}) reached",
            )

        return RiskCheckResult(approved=True)

    def record_pnl(self, pnl: Decimal) -> None:
        """Record P&L from a fill.

        Args:
            pnl: Profit/loss amount
        """
        self._daily_pnl += pnl

    def order_submitted(self) -> None:
        """Track that an order was submitted."""
        self._open_order_count += 1

    def order_completed(self) -> None:
        """Track that an order was completed (filled, cancelled, rejected)."""
        self._open_order_count = max(0, self._open_order_count - 1)

    def reset_daily(self) -> None:
        """Reset daily counters. Call at market open."""
        self._daily_pnl = Decimal("0")

    @property
    def daily_pnl(self) -> Decimal:
        """Get current daily P&L."""
        return self._daily_pnl

    @property
    def open_order_count(self) -> int:
        """Get current open order count."""
        return self._open_order_count
