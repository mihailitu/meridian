"""Unit tests for alerts module."""

from datetime import datetime, timedelta

import pytest

from axtrade.alerts import (
    Alert,
    AlertCategory,
    AlertChannel,
    AlertRepository,
    AlertService,
    AlertSeverity,
    CallbackChannel,
    LogChannel,
)


class TestAlert:
    """Tests for Alert dataclass."""

    def test_create_alert(self) -> None:
        alert = Alert(
            severity=AlertSeverity.WARNING,
            category=AlertCategory.SYSTEM,
            title="Test Alert",
            message="This is a test",
            source="test",
        )

        assert alert.severity == AlertSeverity.WARNING
        assert alert.category == AlertCategory.SYSTEM
        assert alert.title == "Test Alert"
        assert alert.message == "This is a test"
        assert alert.source == "test"
        assert alert.id is not None
        assert alert.timestamp is not None
        assert alert.acknowledged is False

    def test_acknowledge_alert(self) -> None:
        alert = Alert(
            severity=AlertSeverity.INFO,
            category=AlertCategory.TRADING,
            title="Order Filled",
            message="Order 123 filled",
            source="oms",
        )

        assert alert.acknowledged is False
        alert.acknowledge(by="user")

        assert alert.acknowledged is True
        assert alert.acknowledged_by == "user"
        assert alert.acknowledged_at is not None

    def test_to_dict(self) -> None:
        alert = Alert(
            severity=AlertSeverity.ERROR,
            category=AlertCategory.DATA,
            title="Connection Lost",
            message="Lost connection to data feed",
            source="gateway",
            metadata={"feed": "nasdaq"},
        )

        data = alert.to_dict()

        assert data["severity"] == "error"
        assert data["category"] == "data"
        assert data["title"] == "Connection Lost"
        assert data["metadata"] == {"feed": "nasdaq"}
        assert "id" in data
        assert "timestamp" in data


class TestAlertRepository:
    """Tests for AlertRepository."""

    def test_add_and_get(self) -> None:
        repo = AlertRepository(max_alerts=100)
        alert = Alert(
            severity=AlertSeverity.INFO,
            category=AlertCategory.SYSTEM,
            title="Test",
            message="Test message",
            source="test",
        )

        repo.add(alert)

        assert len(repo) == 1
        assert repo.get_by_id(alert.id) == alert

    def test_get_recent(self) -> None:
        repo = AlertRepository(max_alerts=100)

        # Add multiple alerts
        for i in range(10):
            repo.add(
                Alert(
                    severity=AlertSeverity.INFO,
                    category=AlertCategory.SYSTEM,
                    title=f"Alert {i}",
                    message=f"Message {i}",
                    source="test",
                )
            )

        recent = repo.get_recent(limit=5)
        assert len(recent) == 5
        # Most recent first
        assert recent[0].title == "Alert 9"

    def test_filter_by_severity(self) -> None:
        repo = AlertRepository()

        repo.add(
            Alert(
                severity=AlertSeverity.INFO,
                category=AlertCategory.SYSTEM,
                title="Info",
                message="Info message",
                source="test",
            )
        )
        repo.add(
            Alert(
                severity=AlertSeverity.ERROR,
                category=AlertCategory.SYSTEM,
                title="Error",
                message="Error message",
                source="test",
            )
        )

        errors = repo.get_by_severity(AlertSeverity.ERROR)
        assert len(errors) == 1
        assert errors[0].title == "Error"

    def test_filter_by_category(self) -> None:
        repo = AlertRepository()

        repo.add(
            Alert(
                severity=AlertSeverity.INFO,
                category=AlertCategory.SYSTEM,
                title="System",
                message="System message",
                source="test",
            )
        )
        repo.add(
            Alert(
                severity=AlertSeverity.INFO,
                category=AlertCategory.TRADING,
                title="Trading",
                message="Trading message",
                source="test",
            )
        )

        trading = repo.get_by_category(AlertCategory.TRADING)
        assert len(trading) == 1
        assert trading[0].title == "Trading"

    def test_acknowledge(self) -> None:
        repo = AlertRepository()
        alert = Alert(
            severity=AlertSeverity.WARNING,
            category=AlertCategory.RISK,
            title="Risk Alert",
            message="Position limit approaching",
            source="risk",
        )
        repo.add(alert)

        assert repo.get_unacknowledged_count() == 1

        result = repo.acknowledge(alert.id)
        assert result is True
        assert repo.get_unacknowledged_count() == 0

    def test_acknowledge_nonexistent(self) -> None:
        repo = AlertRepository()
        result = repo.acknowledge("nonexistent-id")
        assert result is False

    def test_max_alerts_rotation(self) -> None:
        repo = AlertRepository(max_alerts=5)

        for i in range(10):
            repo.add(
                Alert(
                    severity=AlertSeverity.INFO,
                    category=AlertCategory.SYSTEM,
                    title=f"Alert {i}",
                    message=f"Message {i}",
                    source="test",
                )
            )

        assert len(repo) == 5
        # Oldest should be removed
        recent = repo.get_recent(limit=10)
        titles = [a.title for a in recent]
        assert "Alert 0" not in titles
        assert "Alert 9" in titles

    def test_counts_by_severity(self) -> None:
        repo = AlertRepository()

        repo.add(
            Alert(
                severity=AlertSeverity.INFO,
                category=AlertCategory.SYSTEM,
                title="Info 1",
                message="",
                source="test",
            )
        )
        repo.add(
            Alert(
                severity=AlertSeverity.INFO,
                category=AlertCategory.SYSTEM,
                title="Info 2",
                message="",
                source="test",
            )
        )
        repo.add(
            Alert(
                severity=AlertSeverity.ERROR,
                category=AlertCategory.SYSTEM,
                title="Error",
                message="",
                source="test",
            )
        )

        counts = repo.get_counts_by_severity()
        assert counts["info"] == 2
        assert counts["error"] == 1

    def test_clear(self) -> None:
        repo = AlertRepository()
        repo.add(
            Alert(
                severity=AlertSeverity.INFO,
                category=AlertCategory.SYSTEM,
                title="Test",
                message="",
                source="test",
            )
        )

        assert len(repo) == 1
        repo.clear()
        assert len(repo) == 0


class TestLogChannel:
    """Tests for LogChannel."""

    @pytest.fixture
    def repo(self) -> AlertRepository:
        return AlertRepository()

    def test_send_stores_in_repo(self, repo: AlertRepository) -> None:
        channel = LogChannel(repository=repo)
        alert = Alert(
            severity=AlertSeverity.WARNING,
            category=AlertCategory.SYSTEM,
            title="Test",
            message="Test message",
            source="test",
        )

        import asyncio

        result = asyncio.get_event_loop().run_until_complete(channel.send(alert))

        assert result is True
        assert len(repo) == 1
        assert repo.get_by_id(alert.id) is not None

    def test_send_calls_broadcast(self, repo: AlertRepository) -> None:
        broadcast_called = []

        def broadcast(alert: Alert) -> None:
            broadcast_called.append(alert)

        channel = LogChannel(repository=repo, broadcast_callback=broadcast)
        alert = Alert(
            severity=AlertSeverity.INFO,
            category=AlertCategory.TRADING,
            title="Order",
            message="Order filled",
            source="oms",
        )

        import asyncio

        asyncio.get_event_loop().run_until_complete(channel.send(alert))

        assert len(broadcast_called) == 1
        assert broadcast_called[0].id == alert.id


class TestCallbackChannel:
    """Tests for CallbackChannel."""

    def test_callback_invoked(self) -> None:
        received = []

        def callback(alert: Alert) -> bool:
            received.append(alert)
            return True

        channel = CallbackChannel(callback=callback, name="test-channel")
        alert = Alert(
            severity=AlertSeverity.ERROR,
            category=AlertCategory.SYSTEM,
            title="Error",
            message="An error occurred",
            source="test",
        )

        import asyncio

        result = asyncio.get_event_loop().run_until_complete(channel.send(alert))

        assert result is True
        assert len(received) == 1

    def test_severity_filter(self) -> None:
        received = []

        def callback(alert: Alert) -> bool:
            received.append(alert)
            return True

        channel = CallbackChannel(
            callback=callback,
            name="errors-only",
            min_severity=AlertSeverity.ERROR,
        )

        info_alert = Alert(
            severity=AlertSeverity.INFO,
            category=AlertCategory.SYSTEM,
            title="Info",
            message="",
            source="test",
        )
        error_alert = Alert(
            severity=AlertSeverity.ERROR,
            category=AlertCategory.SYSTEM,
            title="Error",
            message="",
            source="test",
        )

        assert channel.should_send(info_alert) is False
        assert channel.should_send(error_alert) is True


class TestAlertService:
    """Tests for AlertService."""

    @pytest.fixture
    def service(self) -> AlertService:
        return AlertService(channels=[], default_dedupe_seconds=60)

    async def test_send_creates_alert(self, service: AlertService) -> None:
        received = []

        class TestChannel(AlertChannel):
            @property
            def name(self) -> str:
                return "test"

            async def send(self, alert: Alert) -> bool:
                received.append(alert)
                return True

        service.add_channel(TestChannel())

        alert = await service.send(
            severity=AlertSeverity.WARNING,
            category=AlertCategory.SYSTEM,
            title="Test Alert",
            message="This is a test",
            source="test",
        )

        assert alert is not None
        assert alert.title == "Test Alert"
        assert len(received) == 1

    async def test_deduplication(self, service: AlertService) -> None:
        received = []

        class TestChannel(AlertChannel):
            @property
            def name(self) -> str:
                return "test"

            async def send(self, alert: Alert) -> bool:
                received.append(alert)
                return True

        service.add_channel(TestChannel())

        # First alert should go through
        alert1 = await service.send(
            severity=AlertSeverity.ERROR,
            category=AlertCategory.SYSTEM,
            title="Connection Lost",
            message="Lost connection",
            source="gateway",
        )
        assert alert1 is not None

        # Same alert within window should be deduplicated
        alert2 = await service.send(
            severity=AlertSeverity.ERROR,
            category=AlertCategory.SYSTEM,
            title="Connection Lost",
            message="Lost connection again",
            source="gateway",
        )
        assert alert2 is None  # Deduplicated

        assert len(received) == 1

    async def test_convenience_methods(self, service: AlertService) -> None:
        received = []

        class TestChannel(AlertChannel):
            @property
            def name(self) -> str:
                return "test"

            async def send(self, alert: Alert) -> bool:
                received.append(alert)
                return True

        service.add_channel(TestChannel())

        # Test each convenience method with unique titles to avoid deduplication
        await service.info("Info Alert", "Info message", source="test")
        await service.warning("Warning Alert", "Warning message", source="test")
        await service.error("Error Alert", "Error message", source="test")
        await service.critical("Critical Alert", "Critical message", source="test")

        assert len(received) == 4
        severities = [a.severity for a in received]
        assert AlertSeverity.INFO in severities
        assert AlertSeverity.WARNING in severities
        assert AlertSeverity.ERROR in severities
        assert AlertSeverity.CRITICAL in severities

    async def test_custom_dedupe_key(self, service: AlertService) -> None:
        received = []

        class TestChannel(AlertChannel):
            @property
            def name(self) -> str:
                return "test"

            async def send(self, alert: Alert) -> bool:
                received.append(alert)
                return True

        service.add_channel(TestChannel())

        # Different titles but same dedupe key
        alert1 = await service.send(
            severity=AlertSeverity.WARNING,
            category=AlertCategory.SYSTEM,
            title="Alert 1",
            message="First",
            source="test",
            dedupe_key="same-key",
        )
        alert2 = await service.send(
            severity=AlertSeverity.WARNING,
            category=AlertCategory.SYSTEM,
            title="Alert 2",
            message="Second",
            source="test",
            dedupe_key="same-key",
        )

        assert alert1 is not None
        assert alert2 is None  # Deduplicated by key

    async def test_no_deduplication_with_zero_window(self, service: AlertService) -> None:
        received = []

        class TestChannel(AlertChannel):
            @property
            def name(self) -> str:
                return "test"

            async def send(self, alert: Alert) -> bool:
                received.append(alert)
                return True

        service.add_channel(TestChannel())

        alert1 = await service.send(
            severity=AlertSeverity.INFO,
            category=AlertCategory.SYSTEM,
            title="Repeat Alert",
            message="First",
            source="test",
            dedupe_seconds=0,
        )
        alert2 = await service.send(
            severity=AlertSeverity.INFO,
            category=AlertCategory.SYSTEM,
            title="Repeat Alert",
            message="Second",
            source="test",
            dedupe_seconds=0,
        )

        assert alert1 is not None
        assert alert2 is not None
        assert len(received) == 2

    def test_cleanup_dedupe_cache(self, service: AlertService) -> None:
        # Manually add old entries
        old_time = datetime.utcnow() - timedelta(hours=2)
        service._recent_alerts["old-key"] = old_time
        service._recent_alerts["new-key"] = datetime.utcnow()

        removed = service.cleanup_dedupe_cache(max_age_seconds=3600)

        assert removed == 1
        assert "old-key" not in service._recent_alerts
        assert "new-key" in service._recent_alerts
