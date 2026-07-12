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


class StrategyStatusResponse(BaseModel):
    """Strategy status for list endpoint."""

    model_config = ConfigDict(from_attributes=True)

    strategy_id: str
    name: str
    type: str
    enabled: bool
    position_count: int
    daily_pnl: Decimal


class StrategyDetailResponse(BaseModel):
    """Detailed strategy information."""

    model_config = ConfigDict(from_attributes=True)

    strategy_id: str
    name: str
    type: str
    enabled: bool
    config: dict
    position_count: int
    daily_pnl: Decimal
    positions: list[PositionResponse]
    recent_orders: list[OrderResponse]


class StrategyPerformanceResponse(BaseModel):
    """Strategy performance metrics."""

    model_config = ConfigDict(from_attributes=True)

    strategy_id: str
    total_pnl: Decimal
    trade_count: int
    win_rate: float
    avg_trade_pnl: Decimal
    profit_factor: float
    sharpe_ratio: float | None
    sortino_ratio: float | None
    max_drawdown: float
    avg_trade_duration_hours: float
    largest_win: Decimal
    largest_loss: Decimal


class RegimeCurrentResponse(BaseModel):
    """Current market regime for a symbol."""

    symbol: str
    interval: str
    regime: str | None
    trend: str | None
    volatility: str | None
    trend_strength: float | None
    volatility_percentile: float | None
    timestamp: datetime


class RegimeHistoryPoint(BaseModel):
    """Single point in regime history."""

    timestamp: datetime
    regime: str
    trend: str
    volatility: str
    trend_strength: float
    volatility_percentile: float


class RegimeHistoryResponse(BaseModel):
    """Historical regime data for a symbol."""

    symbol: str
    interval: str
    history: list[RegimeHistoryPoint]


class RegimeSummaryResponse(BaseModel):
    """Regime summary for a single symbol."""

    symbol: str
    regime: str | None
    trend: str | None
    volatility: str | None
    last_price: float | None
    timestamp: datetime | None


class DiscoveredSymbolResponse(BaseModel):
    """A discovered symbol from screening."""

    symbol: str
    source: str
    score: float
    price: float | None
    volume: int | None
    change_pct: float | None
    discovered_at: str
    metadata: dict


class ScreenerResultResponse(BaseModel):
    """Result from running a screener."""

    screener_name: str
    screener_type: str
    match_count: int
    total_scanned: int
    scan_time_ms: float
    timestamp: str
    symbols: list[DiscoveredSymbolResponse]


class ScreenerSummaryResponse(BaseModel):
    """Summary info about a screener."""

    name: str
    type: str
    params: dict


class DiscoveryStateResponse(BaseModel):
    """Current state of the discovery service."""

    active_screeners: list[str]
    last_scan: str | None
    total_discovered: int
    is_scanning: bool


class AddSymbolRequest(BaseModel):
    """Request to add a symbol manually."""

    symbol: str
    price: float | None = None
    notes: str | None = None


class DiscoveryCommandAcceptedResponse(BaseModel):
    """Acknowledgment that a discovery control command was published.

    Discovery scanning runs in the strategy-runner process (audit P1-3); the
    API only publishes commands on axtrade:discovery:control, it can't return
    the command's results synchronously.
    """

    status: str = "accepted"
    command: str
    message: str


class GatewayStatusResponse(BaseModel):
    """Gateway status and adapter information."""

    current_adapter: str
    preferred_adapter: str | None
    available_adapters: list[str]
    requires_restart: bool


class GatewayPreferenceRequest(BaseModel):
    """Request to set preferred gateway adapter."""

    adapter: str
