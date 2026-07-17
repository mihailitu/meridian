"""WebSocket handler for real-time updates."""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..dependencies import state
from ..schemas import DashboardData, PnLSummary, PositionResponse

if TYPE_CHECKING:
    from axtrade.alerts import Alert

router = APIRouter()

# Pending alerts to broadcast (for thread safety with async)
_pending_alerts: list[dict] = []


class ConnectionManager:
    """Manages WebSocket connections."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and track a new connection."""
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a disconnected client."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict) -> None:
        """Send message to all connected clients."""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

    def queue_broadcast(self, message: dict) -> None:
        """Queue a message to be broadcast (sync-safe)."""
        _pending_alerts.append(message)


manager = ConnectionManager()


def broadcast_alert(alert: "Alert") -> None:
    """Queue an alert for WebSocket broadcast.

    This is called synchronously from the LogChannel, so we queue
    the alert to be picked up by the async WebSocket loop.

    Args:
        alert: Alert to broadcast
    """
    message = {
        "type": "alert",
        "data": alert.to_dict(),
    }
    manager.queue_broadcast(message)


async def get_dashboard_data() -> DashboardData:
    """Fetch current dashboard data."""
    if state.position_repo is None or state.order_repo is None:
        return DashboardData(
            positions=[],
            pnl=PnLSummary(
                daily_realized=Decimal("0"),
                daily_unrealized=Decimal("0"),
                daily_total=Decimal("0"),
                cumulative_realized=Decimal("0"),
            ),
            timestamp=datetime.now(timezone.utc),
        )

    # Get positions
    positions = await state.position_repo.get_open_positions()
    position_responses = [
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

    # Get P&L
    daily_realized = await state.order_repo.get_daily_realized_pnl()
    daily_unrealized = sum(
        (pos.unrealized_pnl or Decimal("0")) for pos in positions
    )
    cumulative_realized = await state.order_repo.get_total_realized_pnl()

    pnl = PnLSummary(
        daily_realized=daily_realized,
        daily_unrealized=daily_unrealized,
        daily_total=daily_realized + daily_unrealized,
        cumulative_realized=cumulative_realized,
    )

    return DashboardData(
        positions=position_responses,
        pnl=pnl,
        timestamp=datetime.now(timezone.utc),
    )


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    """WebSocket endpoint for real-time dashboard updates."""
    await manager.connect(websocket)
    try:
        while True:
            # Send any pending alerts first
            while _pending_alerts:
                alert_msg = _pending_alerts.pop(0)
                await manager.broadcast(alert_msg)

            # Send dashboard updates every second
            data = await get_dashboard_data()
            message = {
                "type": "dashboard",
                "data": data.model_dump(mode="json"),
            }
            await websocket.send_json(message)
            await asyncio.sleep(1)
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
