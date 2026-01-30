"""System health monitoring."""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import TYPE_CHECKING, Any

import structlog

from .service import AlertService
from .types import AlertCategory, AlertSeverity

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from axtrade.common.db import DatabasePool
    from axtrade.oms import BrokerProtocol

logger = structlog.get_logger()


class HealthStatus(Enum):
    """Health status levels."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ComponentHealth:
    """Health status of a single component."""

    name: str
    status: HealthStatus
    latency_ms: float | None = None
    last_check: datetime = field(default_factory=datetime.utcnow)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "status": self.status.value,
            "latency_ms": self.latency_ms,
            "last_check": self.last_check.isoformat(),
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class SystemHealth:
    """Aggregate system health status."""

    overall: HealthStatus
    components: dict[str, ComponentHealth]
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "overall": self.overall.value,
            "components": {k: v.to_dict() for k, v in self.components.items()},
            "timestamp": self.timestamp.isoformat(),
        }


class HealthMonitor:
    """Monitor system component health.

    Features:
    - Periodic health checks for Redis, Database, Broker
    - Heartbeat tracking for services
    - Alert generation on status changes
    """

    def __init__(
        self,
        alert_service: AlertService | None = None,
        heartbeat_timeout: float = 30.0,
        latency_warning_ms: float = 1000.0,
    ) -> None:
        """Initialize health monitor.

        Args:
            alert_service: Service to send alerts through
            heartbeat_timeout: Seconds before heartbeat is considered missed
            latency_warning_ms: Latency threshold for warnings
        """
        self._alert_service = alert_service
        self._heartbeat_timeout = heartbeat_timeout
        self._latency_warning_ms = latency_warning_ms

        self._components: dict[str, ComponentHealth] = {}
        self._heartbeats: dict[str, datetime] = {}
        self._previous_status: dict[str, HealthStatus] = {}

    async def check_redis(self, redis: "Redis") -> ComponentHealth:
        """Check Redis connectivity.

        Args:
            redis: Redis client

        Returns:
            ComponentHealth for Redis
        """
        start = time.perf_counter()
        try:
            await redis.ping()
            latency_ms = (time.perf_counter() - start) * 1000

            status = HealthStatus.HEALTHY
            error = None

            if latency_ms > self._latency_warning_ms:
                status = HealthStatus.DEGRADED
                error = f"High latency: {latency_ms:.0f}ms"

        except Exception as e:
            latency_ms = None
            status = HealthStatus.UNHEALTHY
            error = str(e)

        health = ComponentHealth(
            name="redis",
            status=status,
            latency_ms=latency_ms,
            error=error,
        )
        await self._update_component("redis", health)
        return health

    async def check_database(self, pool: "DatabasePool") -> ComponentHealth:
        """Check database connectivity.

        Args:
            pool: Database connection pool

        Returns:
            ComponentHealth for database
        """
        start = time.perf_counter()
        try:
            async with pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            latency_ms = (time.perf_counter() - start) * 1000

            status = HealthStatus.HEALTHY
            error = None

            if latency_ms > self._latency_warning_ms:
                status = HealthStatus.DEGRADED
                error = f"High latency: {latency_ms:.0f}ms"

        except Exception as e:
            latency_ms = None
            status = HealthStatus.UNHEALTHY
            error = str(e)

        health = ComponentHealth(
            name="database",
            status=status,
            latency_ms=latency_ms,
            error=error,
        )
        await self._update_component("database", health)
        return health

    async def check_broker(self, broker: "BrokerProtocol") -> ComponentHealth:
        """Check broker connectivity.

        Args:
            broker: Broker protocol instance

        Returns:
            ComponentHealth for broker
        """
        start = time.perf_counter()
        try:
            connected = await broker.is_connected()
            latency_ms = (time.perf_counter() - start) * 1000

            if connected:
                status = HealthStatus.HEALTHY
                error = None
            else:
                status = HealthStatus.UNHEALTHY
                error = "Broker not connected"

        except Exception as e:
            latency_ms = None
            status = HealthStatus.UNHEALTHY
            error = str(e)

        health = ComponentHealth(
            name="broker",
            status=status,
            latency_ms=latency_ms,
            error=error,
        )
        await self._update_component("broker", health)
        return health

    def record_heartbeat(self, component: str) -> None:
        """Record a heartbeat from a component.

        Args:
            component: Component name
        """
        self._heartbeats[component] = datetime.utcnow()

    async def check_heartbeats(self) -> list[ComponentHealth]:
        """Check all registered heartbeats for timeouts.

        Returns:
            List of component health statuses
        """
        results = []
        now = datetime.utcnow()
        timeout = timedelta(seconds=self._heartbeat_timeout)

        for component, last_beat in self._heartbeats.items():
            elapsed = now - last_beat

            if elapsed < timeout:
                status = HealthStatus.HEALTHY
                error = None
            elif elapsed < timeout * 2:
                status = HealthStatus.DEGRADED
                error = f"Heartbeat delayed: {elapsed.total_seconds():.1f}s"
            else:
                status = HealthStatus.UNHEALTHY
                error = f"Heartbeat timeout: {elapsed.total_seconds():.1f}s"

            health = ComponentHealth(
                name=component,
                status=status,
                last_check=now,
                error=error,
                metadata={"last_heartbeat": last_beat.isoformat()},
            )
            await self._update_component(component, health)
            results.append(health)

        return results

    async def _update_component(self, name: str, health: ComponentHealth) -> None:
        """Update component status and send alerts on changes.

        Args:
            name: Component name
            health: New health status
        """
        previous = self._previous_status.get(name)
        self._components[name] = health
        self._previous_status[name] = health.status

        # Send alert on status change
        if previous is not None and previous != health.status:
            await self._send_status_change_alert(name, previous, health)

    async def _send_status_change_alert(
        self,
        component: str,
        previous: HealthStatus,
        current: ComponentHealth,
    ) -> None:
        """Send alert for status change.

        Args:
            component: Component name
            previous: Previous status
            current: Current health
        """
        if self._alert_service is None:
            return

        # Determine severity based on new status
        if current.status == HealthStatus.UNHEALTHY:
            severity = AlertSeverity.CRITICAL
            title = f"{component.title()} Unhealthy"
        elif current.status == HealthStatus.DEGRADED:
            severity = AlertSeverity.WARNING
            title = f"{component.title()} Degraded"
        else:
            severity = AlertSeverity.INFO
            title = f"{component.title()} Recovered"

        message = current.error or f"Status changed from {previous.value} to {current.status.value}"

        await self._alert_service.send(
            severity=severity,
            category=AlertCategory.SYSTEM,
            title=title,
            message=message,
            source="health_monitor",
            metadata={
                "component": component,
                "previous_status": previous.value,
                "current_status": current.status.value,
                "latency_ms": current.latency_ms,
            },
            dedupe_key=f"health:{component}",
            dedupe_seconds=10,  # Short window for health changes
        )

    def get_component_health(self, name: str) -> ComponentHealth | None:
        """Get health status of a specific component.

        Args:
            name: Component name

        Returns:
            ComponentHealth if exists
        """
        return self._components.get(name)

    def get_health(self) -> SystemHealth:
        """Get aggregate system health.

        Returns:
            SystemHealth with overall status and component details
        """
        if not self._components:
            return SystemHealth(
                overall=HealthStatus.HEALTHY,
                components={},
            )

        # Calculate overall status (worst of all components)
        statuses = [c.status for c in self._components.values()]

        if any(s == HealthStatus.UNHEALTHY for s in statuses):
            overall = HealthStatus.UNHEALTHY
        elif any(s == HealthStatus.DEGRADED for s in statuses):
            overall = HealthStatus.DEGRADED
        else:
            overall = HealthStatus.HEALTHY

        return SystemHealth(
            overall=overall,
            components=self._components.copy(),
        )

    async def run_all_checks(
        self,
        redis: "Redis | None" = None,
        database: "DatabasePool | None" = None,
        broker: "BrokerProtocol | None" = None,
    ) -> SystemHealth:
        """Run all available health checks.

        Args:
            redis: Redis client (optional)
            database: Database pool (optional)
            broker: Broker protocol (optional)

        Returns:
            Aggregate system health
        """
        checks = []

        if redis is not None:
            checks.append(self.check_redis(redis))
        if database is not None:
            checks.append(self.check_database(database))
        if broker is not None:
            checks.append(self.check_broker(broker))

        # Check heartbeats
        checks.append(self.check_heartbeats())

        # Run all checks concurrently
        await asyncio.gather(*checks, return_exceptions=True)

        return self.get_health()
