"""Alert service for dispatching alerts through channels."""

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog

from .channels import AlertChannel
from .types import Alert, AlertCategory, AlertSeverity

logger = structlog.get_logger()


class AlertService:
    """Central service for creating and dispatching alerts.

    Features:
    - Dispatches to multiple channels
    - Deduplication to prevent alert storms
    - Convenience methods for common severity levels
    """

    def __init__(
        self,
        channels: list[AlertChannel] | None = None,
        default_dedupe_seconds: int = 60,
    ) -> None:
        """Initialize alert service.

        Args:
            channels: List of channels to dispatch alerts to
            default_dedupe_seconds: Default deduplication window
        """
        self._channels = channels or []
        self._default_dedupe_seconds = default_dedupe_seconds
        self._recent_alerts: dict[str, datetime] = {}

    def add_channel(self, channel: AlertChannel) -> None:
        """Add a channel to the service.

        Args:
            channel: Channel to add
        """
        self._channels.append(channel)
        logger.info("Added alert channel", channel=channel.name)

    def remove_channel(self, channel_name: str) -> bool:
        """Remove a channel by name.

        Args:
            channel_name: Name of channel to remove

        Returns:
            True if channel was found and removed
        """
        for i, channel in enumerate(self._channels):
            if channel.name == channel_name:
                self._channels.pop(i)
                logger.info("Removed alert channel", channel=channel_name)
                return True
        return False

    async def send(
        self,
        severity: AlertSeverity,
        category: AlertCategory,
        title: str,
        message: str,
        source: str,
        metadata: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
        dedupe_seconds: int | None = None,
    ) -> Alert | None:
        """Create and dispatch an alert.

        Args:
            severity: Alert severity level
            category: Alert category
            title: Short alert title
            message: Detailed message
            source: Component that raised the alert
            metadata: Additional context data
            dedupe_key: Key for deduplication (defaults to title+source)
            dedupe_seconds: Deduplication window (None to use default)

        Returns:
            Created alert, or None if deduplicated
        """
        # Build dedupe key
        key = dedupe_key or f"{source}:{title}"
        window = (
            dedupe_seconds
            if dedupe_seconds is not None
            else self._default_dedupe_seconds
        )

        # Check deduplication
        if self._is_duplicate(key, window):
            logger.debug(
                "Alert deduplicated",
                key=key,
                window_seconds=window,
            )
            return None

        # Create alert
        alert = Alert(
            severity=severity,
            category=category,
            title=title,
            message=message,
            source=source,
            metadata=metadata or {},
        )

        # Record for deduplication
        self._recent_alerts[key] = datetime.now(timezone.utc)

        # Dispatch to channels
        await self._dispatch(alert)

        return alert

    async def _dispatch(self, alert: Alert) -> None:
        """Dispatch alert to all applicable channels.

        Args:
            alert: Alert to dispatch
        """
        for channel in self._channels:
            if channel.should_send(alert):
                try:
                    await channel.send(alert)
                except Exception as e:
                    logger.error(
                        "Failed to send alert through channel",
                        channel=channel.name,
                        alert_id=alert.id,
                        error=str(e),
                    )

    def _is_duplicate(self, key: str, window_seconds: int) -> bool:
        """Check if alert is a duplicate within the window.

        Args:
            key: Deduplication key
            window_seconds: Window in seconds

        Returns:
            True if duplicate
        """
        if window_seconds <= 0:
            return False

        last_time = self._recent_alerts.get(key)
        if last_time is None:
            return False

        elapsed = datetime.now(timezone.utc) - last_time
        return elapsed < timedelta(seconds=window_seconds)

    def cleanup_dedupe_cache(self, max_age_seconds: int = 3600) -> int:
        """Remove old entries from deduplication cache.

        Args:
            max_age_seconds: Maximum age of entries to keep

        Returns:
            Number of entries removed
        """
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_age_seconds)
        old_keys = [k for k, v in self._recent_alerts.items() if v < cutoff]
        for key in old_keys:
            del self._recent_alerts[key]
        return len(old_keys)

    # Convenience methods

    async def info(
        self,
        title: str,
        message: str,
        source: str,
        category: AlertCategory = AlertCategory.SYSTEM,
        **kwargs: Any,
    ) -> Alert | None:
        """Send an INFO level alert."""
        return await self.send(
            severity=AlertSeverity.INFO,
            category=category,
            title=title,
            message=message,
            source=source,
            **kwargs,
        )

    async def warning(
        self,
        title: str,
        message: str,
        source: str,
        category: AlertCategory = AlertCategory.SYSTEM,
        **kwargs: Any,
    ) -> Alert | None:
        """Send a WARNING level alert."""
        return await self.send(
            severity=AlertSeverity.WARNING,
            category=category,
            title=title,
            message=message,
            source=source,
            **kwargs,
        )

    async def error(
        self,
        title: str,
        message: str,
        source: str,
        category: AlertCategory = AlertCategory.SYSTEM,
        **kwargs: Any,
    ) -> Alert | None:
        """Send an ERROR level alert."""
        return await self.send(
            severity=AlertSeverity.ERROR,
            category=category,
            title=title,
            message=message,
            source=source,
            **kwargs,
        )

    async def critical(
        self,
        title: str,
        message: str,
        source: str,
        category: AlertCategory = AlertCategory.SYSTEM,
        **kwargs: Any,
    ) -> Alert | None:
        """Send a CRITICAL level alert."""
        return await self.send(
            severity=AlertSeverity.CRITICAL,
            category=category,
            title=title,
            message=message,
            source=source,
            **kwargs,
        )
