"""Health API endpoints."""

from fastapi import APIRouter, Depends

from axtrade.alerts import HealthMonitor

from ..dependencies import get_health_monitor

router = APIRouter()


@router.get("/health/detailed")
async def get_detailed_health(
    health_monitor: HealthMonitor = Depends(get_health_monitor),
) -> dict:
    """Get detailed system health status.

    Returns:
        System health with component details
    """
    health = health_monitor.get_health()
    return health.to_dict()


@router.get("/health/components/{component}")
async def get_component_health(
    component: str,
    health_monitor: HealthMonitor = Depends(get_health_monitor),
) -> dict:
    """Get health status of a specific component.

    Args:
        component: Component name

    Returns:
        Component health details
    """
    component_health = health_monitor.get_component_health(component)
    if component_health is None:
        return {"name": component, "status": "unknown", "error": "Component not monitored"}
    return component_health.to_dict()
