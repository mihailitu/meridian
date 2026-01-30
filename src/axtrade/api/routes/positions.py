"""Position API endpoints."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from axtrade.oms.repository import PositionRepository

from ..dependencies import get_position_repo
from ..schemas import PositionResponse

router = APIRouter()


@router.get("/positions", response_model=list[PositionResponse])
async def get_positions(
    strategy_id: Optional[str] = None,
    position_repo: PositionRepository = Depends(get_position_repo),
) -> list[PositionResponse]:
    """Get all open positions."""
    positions = await position_repo.get_open_positions(strategy_id)
    return [
        PositionResponse(
            symbol=pos.symbol,
            side=pos.side,
            quantity=pos.quantity,
            avg_entry_price=pos.avg_entry_price,
            current_price=pos.current_price,
            unrealized_pnl=pos.unrealized_pnl,
            strategy_id=pos.strategy_id,
        )
        for pos in positions
    ]


@router.get("/positions/{symbol}", response_model=PositionResponse)
async def get_position(
    symbol: str,
    strategy_id: Optional[str] = None,
    position_repo: PositionRepository = Depends(get_position_repo),
) -> PositionResponse:
    """Get position for a specific symbol."""
    positions = await position_repo.get_open_positions(strategy_id)
    for pos in positions:
        if pos.symbol == symbol:
            return PositionResponse(
                symbol=pos.symbol,
                side=pos.side,
                quantity=pos.quantity,
                avg_entry_price=pos.avg_entry_price,
                current_price=pos.current_price,
                unrealized_pnl=pos.unrealized_pnl,
                strategy_id=pos.strategy_id,
            )
    raise HTTPException(status_code=404, detail=f"Position not found for {symbol}")
