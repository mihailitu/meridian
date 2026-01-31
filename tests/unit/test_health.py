"""Unit tests for health monitoring."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from axtrade.alerts import (
    AlertRepository,
    AlertService,
    ComponentHealth,
    HealthMonitor,
    HealthStatus,
    LogChannel,
    SystemHealth,
)


class TestComponentHealth:
    """Tests for ComponentHealth dataclass."""

    def test_create_healthy(self) -> None:
        health = ComponentHealth(
            name="redis",
            status=HealthStatus.HEALTHY,
            latency_ms=5.0,
        )

        assert health.name == "redis"
        assert health.status == HealthStatus.HEALTHY
        assert health.latency_ms == 5.0
        assert health.error is None

    def test_create_unhealthy(self) -> None:
        health = ComponentHealth(
            name="database",
            status=HealthStatus.UNHEALTHY,
            error="Connection refused",
        )

        assert health.status == HealthStatus.UNHEALTHY
        assert health.error == "Connection refused"

    def test_to_dict(self) -> None:
        health = ComponentHealth(
            name="broker",
            status=HealthStatus.DEGRADED,
            latency_ms=1500.0,
            error="High latency",
        )

        data = health.to_dict()

        assert data["name"] == "broker"
        assert data["status"] == "degraded"
        assert data["latency_ms"] == 1500.0
        assert data["error"] == "High latency"


class TestSystemHealth:
    """Tests for SystemHealth dataclass."""

    def test_create(self) -> None:
        components = {
            "redis": ComponentHealth(name="redis", status=HealthStatus.HEALTHY),
            "database": ComponentHealth(name="database", status=HealthStatus.HEALTHY),
        }

        health = SystemHealth(
            overall=HealthStatus.HEALTHY,
            components=components,
        )

        assert health.overall == HealthStatus.HEALTHY
        assert len(health.components) == 2

    def test_to_dict(self) -> None:
        components = {
            "redis": ComponentHealth(name="redis", status=HealthStatus.HEALTHY),
        }

        health = SystemHealth(
            overall=HealthStatus.HEALTHY,
            components=components,
        )

        data = health.to_dict()

        assert data["overall"] == "healthy"
        assert "redis" in data["components"]
        assert data["components"]["redis"]["status"] == "healthy"


class TestHealthMonitor:
    """Tests for HealthMonitor."""

    @pytest.fixture
    def monitor(self) -> HealthMonitor:
        return HealthMonitor(alert_service=None)

    async def test_check_redis_healthy(self, monitor: HealthMonitor) -> None:
        redis_mock = AsyncMock()
        redis_mock.ping = AsyncMock(return_value=True)

        health = await monitor.check_redis(redis_mock)

        assert health.name == "redis"
        assert health.status == HealthStatus.HEALTHY
        assert health.latency_ms is not None
        assert health.error is None

    async def test_check_redis_unhealthy(self, monitor: HealthMonitor) -> None:
        redis_mock = AsyncMock()
        redis_mock.ping = AsyncMock(side_effect=Exception("Connection refused"))

        health = await monitor.check_redis(redis_mock)

        assert health.status == HealthStatus.UNHEALTHY
        assert "Connection refused" in health.error

    async def test_check_database_healthy(self, monitor: HealthMonitor) -> None:
        pool_mock = MagicMock()
        conn_mock = AsyncMock()
        conn_mock.fetchval = AsyncMock(return_value=1)
        pool_mock.acquire = MagicMock(return_value=AsyncMock(__aenter__=AsyncMock(return_value=conn_mock), __aexit__=AsyncMock()))

        health = await monitor.check_database(pool_mock)

        assert health.name == "database"
        assert health.status == HealthStatus.HEALTHY

    async def test_check_database_unhealthy(self, monitor: HealthMonitor) -> None:
        pool_mock = MagicMock()
        pool_mock.acquire = MagicMock(side_effect=Exception("Pool exhausted"))

        health = await monitor.check_database(pool_mock)

        assert health.status == HealthStatus.UNHEALTHY
        assert "Pool exhausted" in health.error

    async def test_check_broker_connected(self, monitor: HealthMonitor) -> None:
        broker_mock = AsyncMock()
        broker_mock.is_connected = AsyncMock(return_value=True)

        health = await monitor.check_broker(broker_mock)

        assert health.name == "broker"
        assert health.status == HealthStatus.HEALTHY

    async def test_check_broker_disconnected(self, monitor: HealthMonitor) -> None:
        broker_mock = AsyncMock()
        broker_mock.is_connected = AsyncMock(return_value=False)

        health = await monitor.check_broker(broker_mock)

        assert health.status == HealthStatus.UNHEALTHY
        assert "not connected" in health.error.lower()

    def test_record_heartbeat(self, monitor: HealthMonitor) -> None:
        monitor.record_heartbeat("gateway")
        monitor.record_heartbeat("aggregator")

        assert "gateway" in monitor._heartbeats
        assert "aggregator" in monitor._heartbeats

    async def test_check_heartbeats_healthy(self, monitor: HealthMonitor) -> None:
        monitor.record_heartbeat("gateway")

        results = await monitor.check_heartbeats()

        assert len(results) == 1
        assert results[0].name == "gateway"
        assert results[0].status == HealthStatus.HEALTHY

    async def test_check_heartbeats_timeout(self, monitor: HealthMonitor) -> None:
        # Manually set old heartbeat
        monitor._heartbeats["stale-service"] = datetime.now(timezone.utc) - timedelta(minutes=5)

        results = await monitor.check_heartbeats()

        assert len(results) == 1
        assert results[0].status == HealthStatus.UNHEALTHY
        assert "timeout" in results[0].error.lower()

    def test_get_health_empty(self, monitor: HealthMonitor) -> None:
        health = monitor.get_health()

        assert health.overall == HealthStatus.HEALTHY
        assert len(health.components) == 0

    def test_get_health_all_healthy(self, monitor: HealthMonitor) -> None:
        monitor._components["redis"] = ComponentHealth(
            name="redis", status=HealthStatus.HEALTHY
        )
        monitor._components["database"] = ComponentHealth(
            name="database", status=HealthStatus.HEALTHY
        )

        health = monitor.get_health()

        assert health.overall == HealthStatus.HEALTHY

    def test_get_health_one_degraded(self, monitor: HealthMonitor) -> None:
        monitor._components["redis"] = ComponentHealth(
            name="redis", status=HealthStatus.HEALTHY
        )
        monitor._components["database"] = ComponentHealth(
            name="database", status=HealthStatus.DEGRADED
        )

        health = monitor.get_health()

        assert health.overall == HealthStatus.DEGRADED

    def test_get_health_one_unhealthy(self, monitor: HealthMonitor) -> None:
        monitor._components["redis"] = ComponentHealth(
            name="redis", status=HealthStatus.HEALTHY
        )
        monitor._components["database"] = ComponentHealth(
            name="database", status=HealthStatus.UNHEALTHY
        )

        health = monitor.get_health()

        assert health.overall == HealthStatus.UNHEALTHY

    def test_get_component_health(self, monitor: HealthMonitor) -> None:
        monitor._components["redis"] = ComponentHealth(
            name="redis", status=HealthStatus.HEALTHY, latency_ms=3.0
        )

        health = monitor.get_component_health("redis")
        assert health is not None
        assert health.latency_ms == 3.0

        missing = monitor.get_component_health("nonexistent")
        assert missing is None


class TestHealthMonitorAlerts:
    """Tests for health monitor alert generation."""

    @pytest.fixture
    def alert_service(self) -> AlertService:
        repo = AlertRepository()
        service = AlertService(default_dedupe_seconds=1)
        service.add_channel(LogChannel(repository=repo))
        return service

    @pytest.fixture
    def monitor(self, alert_service: AlertService) -> HealthMonitor:
        return HealthMonitor(alert_service=alert_service)

    async def test_alert_on_status_change_to_unhealthy(
        self, monitor: HealthMonitor, alert_service: AlertService
    ) -> None:
        # First check - healthy
        redis_mock = AsyncMock()
        redis_mock.ping = AsyncMock(return_value=True)
        await monitor.check_redis(redis_mock)

        # Second check - unhealthy
        redis_mock.ping = AsyncMock(side_effect=Exception("Connection lost"))
        await monitor.check_redis(redis_mock)

        # Should have generated an alert
        # Check via the channel's repository
        channel = alert_service._channels[0]
        if isinstance(channel, LogChannel):
            alerts = channel._repository.get_recent(limit=10)
            assert len(alerts) >= 1
            assert any("Redis" in a.title for a in alerts)

    async def test_alert_on_recovery(
        self, monitor: HealthMonitor, alert_service: AlertService
    ) -> None:
        # Start unhealthy
        redis_mock = AsyncMock()
        redis_mock.ping = AsyncMock(side_effect=Exception("Connection lost"))
        await monitor.check_redis(redis_mock)

        # Recover
        redis_mock.ping = AsyncMock(return_value=True)
        await monitor.check_redis(redis_mock)

        # Should have recovery alert
        channel = alert_service._channels[0]
        if isinstance(channel, LogChannel):
            alerts = channel._repository.get_recent(limit=10)
            recovery_alerts = [a for a in alerts if "Recovered" in a.title]
            assert len(recovery_alerts) >= 1


class TestHealthMonitorRunAllChecks:
    """Tests for run_all_checks method."""

    async def test_run_all_checks(self) -> None:
        monitor = HealthMonitor()

        redis_mock = AsyncMock()
        redis_mock.ping = AsyncMock(return_value=True)

        health = await monitor.run_all_checks(redis=redis_mock)

        assert health.overall == HealthStatus.HEALTHY
        assert "redis" in health.components

    async def test_run_all_checks_partial(self) -> None:
        monitor = HealthMonitor()

        redis_mock = AsyncMock()
        redis_mock.ping = AsyncMock(return_value=True)

        broker_mock = AsyncMock()
        broker_mock.is_connected = AsyncMock(return_value=False)

        health = await monitor.run_all_checks(redis=redis_mock, broker=broker_mock)

        # One healthy, one unhealthy = overall unhealthy
        assert health.overall == HealthStatus.UNHEALTHY
        assert health.components["redis"].status == HealthStatus.HEALTHY
        assert health.components["broker"].status == HealthStatus.UNHEALTHY
