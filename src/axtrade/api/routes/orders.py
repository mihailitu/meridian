"""Order API endpoints."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from axtrade.oms.repository import OrderRepository

from ..dependencies import get_order_repo
from ..schemas import FillResponse, OrderResponse

router = APIRouter()


@router.get("/orders", response_model=list[OrderResponse])
async def get_orders(
    strategy_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    order_repo: OrderRepository = Depends(get_order_repo),
) -> list[OrderResponse]:
    """Get recent orders with optional filters."""
    orders = await order_repo.get_recent_orders(strategy_id, status, limit)
    return [
        OrderResponse(
            id=str(order.id),
            symbol=order.symbol,
            side=order.side.value,
            quantity=order.quantity,
            order_type=order.order_type.value,
            status=order.status.value,
            limit_price=order.limit_price,
            filled_quantity=order.filled_quantity,
            avg_fill_price=order.avg_fill_price,
            strategy_id=order.strategy_id,
            created_at=order.created_at,
            updated_at=order.updated_at,
        )
        for order in orders
    ]


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    order_repo: OrderRepository = Depends(get_order_repo),
) -> OrderResponse:
    """Get a specific order by ID."""
    try:
        uuid_id = UUID(order_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid order ID format")

    order = await order_repo.get(uuid_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return OrderResponse(
        id=str(order.id),
        symbol=order.symbol,
        side=order.side.value,
        quantity=order.quantity,
        order_type=order.order_type.value,
        status=order.status.value,
        limit_price=order.limit_price,
        filled_quantity=order.filled_quantity,
        avg_fill_price=order.avg_fill_price,
        strategy_id=order.strategy_id,
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


@router.get("/orders/{order_id}/fills", response_model=list[FillResponse])
async def get_order_fills(
    order_id: str,
    order_repo: OrderRepository = Depends(get_order_repo),
) -> list[FillResponse]:
    """Get fills for a specific order."""
    try:
        uuid_id = UUID(order_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid order ID format")

    fills = await order_repo.get_fills_for_order(uuid_id)
    return [
        FillResponse(
            id=str(fill.id),
            order_id=str(fill.order_id),
            symbol=fill.symbol,
            side=fill.side.value,
            quantity=fill.quantity,
            price=fill.price,
            commission=fill.commission,
            strategy_id=fill.strategy_id,
            filled_at=fill.filled_at,
        )
        for fill in fills
    ]


@router.get("/fills", response_model=list[FillResponse])
async def get_fills(
    strategy_id: Optional[str] = None,
    limit: int = 50,
    order_repo: OrderRepository = Depends(get_order_repo),
) -> list[FillResponse]:
    """Get recent fills with optional strategy filter."""
    fills = await order_repo.get_recent_fills(strategy_id, limit)
    return [
        FillResponse(
            id=str(fill.id),
            order_id=str(fill.order_id),
            symbol=fill.symbol,
            side=fill.side.value,
            quantity=fill.quantity,
            price=fill.price,
            commission=fill.commission,
            strategy_id=fill.strategy_id,
            filled_at=fill.filled_at,
        )
        for fill in fills
    ]
