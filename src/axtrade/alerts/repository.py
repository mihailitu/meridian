"""In-memory alert repository with rotation."""

from collections import deque
from threading import Lock

from .types import Alert, AlertCategory, AlertSeverity


class AlertRepository:
    """Thread-safe in-memory alert storage with automatic rotation.

    Stores alerts in a fixed-size deque, automatically removing oldest
    alerts when capacity is exceeded.
    """

    def __init__(self, max_alerts: int = 1000) -> None:
        """Initialize repository.

        Args:
            max_alerts: Maximum number of alerts to store
        """
        self._alerts: deque[Alert] = deque(maxlen=max_alerts)
        self._lock = Lock()

    def add(self, alert: Alert) -> None:
        """Add an alert to the repository.

        Args:
            alert: Alert to store
        """
        with self._lock:
            self._alerts.appendleft(alert)

    def get_by_id(self, alert_id: str) -> Alert | None:
        """Get alert by ID.

        Args:
            alert_id: Alert ID to find

        Returns:
            Alert if found, None otherwise
        """
        with self._lock:
            for alert in self._alerts:
                if alert.id == alert_id:
                    return alert
            return None

    def get_recent(
        self,
        limit: int = 50,
        severity: AlertSeverity | None = None,
        category: AlertCategory | None = None,
        acknowledged: bool | None = None,
    ) -> list[Alert]:
        """Get recent alerts with optional filtering.

        Args:
            limit: Maximum number of alerts to return
            severity: Filter by severity level
            category: Filter by category
            acknowledged: Filter by acknowledged status

        Returns:
            List of matching alerts, most recent first
        """
        with self._lock:
            result = []
            for alert in self._alerts:
                if severity is not None and alert.severity != severity:
                    continue
                if category is not None and alert.category != category:
                    continue
                if acknowledged is not None and alert.acknowledged != acknowledged:
                    continue
                result.append(alert)
                if len(result) >= limit:
                    break
            return result

    def get_by_severity(self, severity: AlertSeverity, limit: int = 100) -> list[Alert]:
        """Get alerts by severity level.

        Args:
            severity: Severity to filter by
            limit: Maximum number of alerts

        Returns:
            List of matching alerts
        """
        return self.get_recent(limit=limit, severity=severity)

    def get_by_category(self, category: AlertCategory, limit: int = 100) -> list[Alert]:
        """Get alerts by category.

        Args:
            category: Category to filter by
            limit: Maximum number of alerts

        Returns:
            List of matching alerts
        """
        return self.get_recent(limit=limit, category=category)

    def acknowledge(self, alert_id: str, by: str = "user") -> bool:
        """Acknowledge an alert.

        Args:
            alert_id: ID of alert to acknowledge
            by: Who acknowledged the alert

        Returns:
            True if alert was found and acknowledged
        """
        with self._lock:
            for alert in self._alerts:
                if alert.id == alert_id:
                    alert.acknowledge(by=by)
                    return True
            return False

    def get_unacknowledged_count(self) -> int:
        """Get count of unacknowledged alerts.

        Returns:
            Number of unacknowledged alerts
        """
        with self._lock:
            return sum(1 for alert in self._alerts if not alert.acknowledged)

    def get_counts_by_severity(self) -> dict[str, int]:
        """Get alert counts grouped by severity.

        Returns:
            Dictionary mapping severity to count
        """
        with self._lock:
            counts: dict[str, int] = {}
            for alert in self._alerts:
                if not alert.acknowledged:
                    key = alert.severity.value
                    counts[key] = counts.get(key, 0) + 1
            return counts

    def clear(self) -> None:
        """Clear all alerts."""
        with self._lock:
            self._alerts.clear()

    def __len__(self) -> int:
        """Get total number of stored alerts."""
        with self._lock:
            return len(self._alerts)
