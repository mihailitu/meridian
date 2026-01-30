"""Pydantic schemas for API responses."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class PositionResponse(BaseModel):
    """Position data for API response."""

    model_config = ConfigDict(from_attributes=True)

    symbol: str
    side: str
    quantity: Decimal
    avg_entry_price: Decimal
    current_price: Decimal | None = None
    unrealized_pnl: Decimal | None = None
    strategy_id: str


class OrderResponse(BaseModel):
    """Order data for API response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    symbol: str
    side: str
    quantity: Decimal
    order_type: str
    status: str
    limit_price: Decimal | None = None
    filled_quantity: Decimal
    avg_fill_price: Decimal | None = None
    strategy_id: str
    created_at: datetime
    updated_at: datetime


class FillResponse(BaseModel):
    """Fill data for API response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    order_id: str
    symbol: str
    side: str
    quantity: Decimal
    price: Decimal
    commission: Decimal
    strategy_id: str
    filled_at: datetime


class PnLSummary(BaseModel):
    """P&L summary for dashboard."""

    daily_realized: Decimal
    daily_unrealized: Decimal
    daily_total: Decimal
    cumulative_realized: Decimal


class StrategyStatus(BaseModel):
    """Strategy status for dashboard."""

    strategy_id: str
    name: str
    enabled: bool
    position_count: int
    daily_pnl: Decimal


class DashboardData(BaseModel):
    """Combined data for dashboard WebSocket updates."""

    positions: list[PositionResponse]
    pnl: PnLSummary
    timestamp: datetime
