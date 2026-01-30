"""OMS data types."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4


class OrderSide(Enum):
    """Order side (buy or sell)."""

    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Order type."""

    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


class OrderStatus(Enum):
    """Order lifecycle status."""

    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIAL = "partial"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_uuid() -> UUID:
    return uuid4()


@dataclass
class Order:
    """A trading order."""

    strategy_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    order_type: OrderType = OrderType.MARKET
    limit_price: Optional[Decimal] = None
    stop_price: Optional[Decimal] = None
    id: UUID = field(default_factory=_new_uuid)
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: Decimal = field(default_factory=lambda: Decimal("0"))
    avg_fill_price: Optional[Decimal] = None
    created_at: datetime = field(default_factory=_utcnow)
    updated_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": str(self.id),
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "order_type": self.order_type.value,
            "quantity": str(self.quantity),
            "limit_price": str(self.limit_price) if self.limit_price else "",
            "stop_price": str(self.stop_price) if self.stop_price else "",
            "status": self.status.value,
            "filled_quantity": str(self.filled_quantity),
            "avg_fill_price": str(self.avg_fill_price) if self.avg_fill_price else "",
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class Fill:
    """An order fill (execution)."""

    order_id: UUID
    strategy_id: str
    symbol: str
    side: OrderSide
    quantity: Decimal
    price: Decimal
    commission: Decimal = field(default_factory=lambda: Decimal("0"))
    id: UUID = field(default_factory=_new_uuid)
    filled_at: datetime = field(default_factory=_utcnow)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": str(self.id),
            "order_id": str(self.order_id),
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": str(self.quantity),
            "price": str(self.price),
            "commission": str(self.commission),
            "filled_at": self.filled_at.isoformat(),
        }


@dataclass
class Position:
    """A trading position."""

    strategy_id: str
    symbol: str
    side: str  # 'long' or 'short'
    quantity: Decimal
    avg_entry_price: Decimal
    current_price: Optional[Decimal] = None
    unrealized_pnl: Optional[Decimal] = None
    realized_pnl: Decimal = field(default_factory=lambda: Decimal("0"))
    id: Optional[UUID] = None
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def is_open(self) -> bool:
        """Check if position is still open."""
        return self.quantity > 0 and self.closed_at is None

    @property
    def market_value(self) -> Optional[Decimal]:
        """Current market value of position."""
        if self.current_price is None:
            return None
        return self.quantity * self.current_price

    def calculate_unrealized_pnl(self, current_price: Decimal) -> Decimal:
        """Calculate unrealized P&L at given price."""
        if self.side == "long":
            return (current_price - self.avg_entry_price) * self.quantity
        else:
            return (self.avg_entry_price - current_price) * self.quantity

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": str(self.id) if self.id else "",
            "strategy_id": self.strategy_id,
            "symbol": self.symbol,
            "side": self.side,
            "quantity": str(self.quantity),
            "avg_entry_price": str(self.avg_entry_price),
            "current_price": str(self.current_price) if self.current_price else "",
            "unrealized_pnl": str(self.unrealized_pnl) if self.unrealized_pnl else "",
            "realized_pnl": str(self.realized_pnl),
        }
