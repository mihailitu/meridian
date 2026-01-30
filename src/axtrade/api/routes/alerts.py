"""Alert API endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query

from axtrade.alerts import AlertCategory, AlertRepository, AlertSeverity

from ..dependencies import get_alert_repo

router = APIRouter()


@router.get("/alerts")
async def get_alerts(
    limit: int = Query(default=50, ge=1, le=500),
    severity: str | None = Query(default=None),
    category: str | None = Query(default=None),
    acknowledged: bool | None = Query(default=None),
    alert_repo: AlertRepository = Depends(get_alert_repo),
) -> list[dict]:
    """Get recent alerts.

    Args:
        limit: Maximum number of alerts to return
        severity: Filter by severity (info, warning, error, critical)
        category: Filter by category (system, trading, risk, data)
        acknowledged: Filter by acknowledged status

    Returns:
        List of alert dictionaries
    """
    # Parse severity if provided
    severity_filter = None
    if severity:
        try:
            severity_filter = AlertSeverity(severity.lower())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid severity: {severity}. Must be one of: info, warning, error, critical",
            )

    # Parse category if provided
    category_filter = None
    if category:
        try:
            category_filter = AlertCategory(category.lower())
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid category: {category}. Must be one of: system, trading, risk, data",
            )

    alerts = alert_repo.get_recent(
        limit=limit,
        severity=severity_filter,
        category=category_filter,
        acknowledged=acknowledged,
    )

    return [alert.to_dict() for alert in alerts]


@router.get("/alerts/counts")
async def get_alert_counts(
    alert_repo: AlertRepository = Depends(get_alert_repo),
) -> dict:
    """Get alert counts by severity.

    Returns:
        Dictionary with counts by severity and total unacknowledged
    """
    counts = alert_repo.get_counts_by_severity()
    return {
        "by_severity": counts,
        "unacknowledged": alert_repo.get_unacknowledged_count(),
        "total": len(alert_repo),
    }


@router.post("/alerts/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    alert_repo: AlertRepository = Depends(get_alert_repo),
) -> dict:
    """Acknowledge an alert.

    Args:
        alert_id: ID of alert to acknowledge

    Returns:
        Success status
    """
    if alert_repo.acknowledge(alert_id):
        return {"success": True, "alert_id": alert_id}
    else:
        raise HTTPException(
            status_code=404,
            detail=f"Alert not found: {alert_id}",
        )
