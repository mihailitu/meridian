"""P&L API endpoints."""

from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends

from axtrade.oms.repository import OrderRepository, PositionRepository

from ..dependencies import get_order_repo, get_position_repo
from ..schemas import PnLSummary

router = APIRouter()


@router.get("/pnl/summary", response_model=PnLSummary)
async def get_pnl_summary(
    strategy_id: Optional[str] = None,
    order_repo: OrderRepository = Depends(get_order_repo),
    position_repo: PositionRepository = Depends(get_position_repo),
) -> PnLSummary:
    """Get P&L summary for dashboard."""
    # Get daily realized P&L from fills
    daily_realized = await order_repo.get_daily_realized_pnl(strategy_id)

    # Get unrealized P&L from open positions
    positions = await position_repo.get_open_positions(strategy_id)
    daily_unrealized = sum(
        (pos.unrealized_pnl or Decimal("0")) for pos in positions
    )

    cumulative_realized = await order_repo.get_total_realized_pnl(strategy_id)

    return PnLSummary(
        daily_realized=daily_realized,
        daily_unrealized=daily_unrealized,
        daily_total=daily_realized + daily_unrealized,
        cumulative_realized=cumulative_realized,
    )
