"""Alert channels for dispatching notifications."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable

import structlog

from .repository import AlertRepository
from .types import Alert, AlertSeverity

if TYPE_CHECKING:
    pass

logger = structlog.get_logger()


class AlertChannel(ABC):
    """Abstract base class for alert channels.

    Implement this to add new notification methods (email, SMS, Slack, etc.)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Channel name for logging and identification."""
        ...

    @abstractmethod
    async def send(self, alert: Alert) -> bool:
        """Send an alert through this channel.

        Args:
            alert: Alert to send

        Returns:
            True if alert was sent successfully
        """
        ...

    def should_send(self, alert: Alert) -> bool:
        """Check if this channel should handle the alert.

        Override to filter alerts by severity, category, etc.

        Args:
            alert: Alert to check

        Returns:
            True if this channel should send the alert
        """
        return True


class LogChannel(AlertChannel):
    """Channel that logs alerts and stores them in repository.

    This is the default channel that makes alerts visible in the frontend.
    """

    def __init__(
        self,
        repository: AlertRepository,
        broadcast_callback: Callable[[Alert], None] | None = None,
    ) -> None:
        """Initialize log channel.

        Args:
            repository: Repository to store alerts
            broadcast_callback: Optional callback to broadcast alert (e.g., WebSocket)
        """
        self._repository = repository
        self._broadcast_callback = broadcast_callback

    @property
    def name(self) -> str:
        return "log"

    async def send(self, alert: Alert) -> bool:
        """Log alert and store in repository.

        Args:
            alert: Alert to log and store

        Returns:
            Always True
        """
        # Log with appropriate level
        log_method = self._get_log_method(alert.severity)
        log_method(
            alert.title,
            alert_id=alert.id,
            category=alert.category.value,
            message=alert.message,
            source=alert.source,
            metadata=alert.metadata,
        )

        # Store in repository
        self._repository.add(alert)

        # Broadcast if callback provided
        if self._broadcast_callback:
            try:
                self._broadcast_callback(alert)
            except Exception as e:
                logger.error("Failed to broadcast alert", error=str(e))

        return True

    def _get_log_method(self, severity: AlertSeverity) -> Callable:
        """Get appropriate structlog method for severity."""
        if severity == AlertSeverity.CRITICAL:
            return logger.critical
        elif severity == AlertSeverity.ERROR:
            return logger.error
        elif severity == AlertSeverity.WARNING:
            return logger.warning
        else:
            return logger.info


class CallbackChannel(AlertChannel):
    """Channel that invokes a callback for each alert.

    Useful for testing or custom integrations.
    """

    def __init__(
        self,
        callback: Callable[[Alert], bool],
        name: str = "callback",
        min_severity: AlertSeverity = AlertSeverity.INFO,
    ) -> None:
        """Initialize callback channel.

        Args:
            callback: Function to call with each alert
            name: Channel name
            min_severity: Minimum severity to handle
        """
        self._callback = callback
        self._name = name
        self._min_severity = min_severity
        self._severity_order = {
            AlertSeverity.INFO: 0,
            AlertSeverity.WARNING: 1,
            AlertSeverity.ERROR: 2,
            AlertSeverity.CRITICAL: 3,
        }

    @property
    def name(self) -> str:
        return self._name

    def should_send(self, alert: Alert) -> bool:
        """Check if alert meets minimum severity."""
        return (
            self._severity_order[alert.severity]
            >= self._severity_order[self._min_severity]
        )

    async def send(self, alert: Alert) -> bool:
        """Invoke callback with alert.

        Args:
            alert: Alert to send

        Returns:
            Result of callback
        """
        try:
            return self._callback(alert)
        except Exception as e:
            logger.error(
                "Callback channel failed",
                channel=self._name,
                error=str(e),
            )
            return False
