"""Shared dependencies for API endpoints."""

from typing import Optional

from axtrade.alerts import AlertRepository, AlertService, HealthMonitor
from axtrade.common import DatabasePool
from axtrade.oms.repository import OrderRepository, PositionRepository


class APIState:
    """Shared state for API endpoints."""

    db_pool: Optional[DatabasePool] = None
    order_repo: Optional[OrderRepository] = None
    position_repo: Optional[PositionRepository] = None
    alert_repo: Optional[AlertRepository] = None
    alert_service: Optional[AlertService] = None
    health_monitor: Optional[HealthMonitor] = None


state = APIState()


def get_order_repo() -> OrderRepository:
    """Get order repository dependency."""
    if state.order_repo is None:
        raise RuntimeError("Order repository not initialized")
    return state.order_repo


def get_position_repo() -> PositionRepository:
    """Get position repository dependency."""
    if state.position_repo is None:
        raise RuntimeError("Position repository not initialized")
    return state.position_repo


def get_alert_repo() -> AlertRepository:
    """Get alert repository dependency."""
    if state.alert_repo is None:
        raise RuntimeError("Alert repository not initialized")
    return state.alert_repo


def get_alert_service() -> AlertService:
    """Get alert service dependency."""
    if state.alert_service is None:
        raise RuntimeError("Alert service not initialized")
    return state.alert_service


def get_health_monitor() -> HealthMonitor:
    """Get health monitor dependency."""
    if state.health_monitor is None:
        raise RuntimeError("Health monitor not initialized")
    return state.health_monitor
