"""Extended unit tests for API endpoints.

Tests for alerts, strategies, and health endpoints.
"""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from axtrade.alerts import Alert, AlertCategory, AlertSeverity
from axtrade.alerts.health import ComponentHealth, HealthStatus, SystemHealth
from axtrade.api.dependencies import state
from axtrade.api.routes import alerts, health, strategies
from axtrade.common import StrategiesConfig, StrategyInstanceConfig
from axtrade.strategies import StrategyState


def create_test_app_extended() -> FastAPI:
    """Create a test app with extended routes."""
    app = FastAPI(title="axtrade API Test Extended")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(alerts.router, prefix="/api", tags=["alerts"])
    app.include_router(health.router, prefix="/api", tags=["health"])
    app.include_router(strategies.router, prefix="/api", tags=["strategies"])

    return app


class TestAlertsEndpoint:
    """Tests for alerts API endpoints."""

    @pytest.fixture
    def mock_alert_repo(self) -> MagicMock:
        """Create a mock alert repository."""
        repo = MagicMock()
        repo.get_recent = MagicMock(return_value=[])
        repo.get_counts_by_severity = MagicMock(return_value={})
        repo.get_unacknowledged_count = MagicMock(return_value=0)
        repo.__len__ = MagicMock(return_value=0)
        repo.acknowledge = MagicMock(return_value=True)
        return repo

    @pytest.fixture
    def client(self, mock_alert_repo) -> TestClient:
        """Create test client with mocked dependencies."""
        state.alert_repo = mock_alert_repo

        app = create_test_app_extended()

        with TestClient(app) as client:
            yield client

        state.alert_repo = None

    def test_get_alerts_empty(self, client: TestClient) -> None:
        """Test get alerts returns empty list."""
        response = client.get("/api/alerts")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_alerts_returns_data(
        self, client: TestClient, mock_alert_repo
    ) -> None:
        """Test get alerts returns alert data."""
        alert = Alert(
            id="test-alert-1",
            severity=AlertSeverity.WARNING,
            category=AlertCategory.TRADING,
            title="Test Alert",
            message="This is a test alert",
            source="test",
            timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
        )
        mock_alert_repo.get_recent.return_value = [alert]

        response = client.get("/api/alerts")
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "test-alert-1"
        assert data[0]["severity"] == "warning"
        assert data[0]["category"] == "trading"
        assert data[0]["title"] == "Test Alert"

    def test_get_alerts_with_limit(
        self, client: TestClient, mock_alert_repo
    ) -> None:
        """Test get alerts respects limit parameter."""
        client.get("/api/alerts?limit=10")
        mock_alert_repo.get_recent.assert_called_once()
        call_kwargs = mock_alert_repo.get_recent.call_args[1]
        assert call_kwargs["limit"] == 10

    def test_get_alerts_with_severity_filter(
        self, client: TestClient, mock_alert_repo
    ) -> None:
        """Test get alerts with severity filter."""
        client.get("/api/alerts?severity=error")
        call_kwargs = mock_alert_repo.get_recent.call_args[1]
        assert call_kwargs["severity"] == AlertSeverity.ERROR

    def test_get_alerts_with_category_filter(
        self, client: TestClient, mock_alert_repo
    ) -> None:
        """Test get alerts with category filter."""
        client.get("/api/alerts?category=risk")
        call_kwargs = mock_alert_repo.get_recent.call_args[1]
        assert call_kwargs["category"] == AlertCategory.RISK

    def test_get_alerts_with_acknowledged_filter(
        self, client: TestClient, mock_alert_repo
    ) -> None:
        """Test get alerts with acknowledged filter."""
        client.get("/api/alerts?acknowledged=true")
        call_kwargs = mock_alert_repo.get_recent.call_args[1]
        assert call_kwargs["acknowledged"] is True

    def test_get_alerts_invalid_severity(self, client: TestClient) -> None:
        """Test get alerts with invalid severity returns 400."""
        response = client.get("/api/alerts?severity=invalid")
        assert response.status_code == 400
        assert "Invalid severity" in response.json()["detail"]

    def test_get_alerts_invalid_category(self, client: TestClient) -> None:
        """Test get alerts with invalid category returns 400."""
        response = client.get("/api/alerts?category=invalid")
        assert response.status_code == 400
        assert "Invalid category" in response.json()["detail"]

    def test_get_alert_counts(
        self, client: TestClient, mock_alert_repo
    ) -> None:
        """Test get alert counts."""
        mock_alert_repo.get_counts_by_severity.return_value = {
            "warning": 5,
            "error": 2,
        }
        mock_alert_repo.get_unacknowledged_count.return_value = 3
        mock_alert_repo.__len__.return_value = 10

        response = client.get("/api/alerts/counts")
        assert response.status_code == 200

        data = response.json()
        assert data["by_severity"]["warning"] == 5
        assert data["by_severity"]["error"] == 2
        assert data["unacknowledged"] == 3
        assert data["total"] == 10

    def test_acknowledge_alert_success(
        self, client: TestClient, mock_alert_repo
    ) -> None:
        """Test acknowledge alert success."""
        mock_alert_repo.acknowledge.return_value = True

        response = client.post("/api/alerts/test-alert-1/acknowledge")
        assert response.status_code == 200

        data = response.json()
        assert data["success"] is True
        assert data["alert_id"] == "test-alert-1"

    def test_acknowledge_alert_not_found(
        self, client: TestClient, mock_alert_repo
    ) -> None:
        """Test acknowledge alert not found."""
        mock_alert_repo.acknowledge.return_value = False

        response = client.post("/api/alerts/nonexistent/acknowledge")
        assert response.status_code == 404
        assert "Alert not found" in response.json()["detail"]


class TestHealthEndpoint:
    """Tests for health API endpoints."""

    @pytest.fixture
    def mock_health_monitor(self) -> MagicMock:
        """Create a mock health monitor."""
        monitor = MagicMock()
        return monitor

    @pytest.fixture
    def client(self, mock_health_monitor) -> TestClient:
        """Create test client with mocked dependencies."""
        state.health_monitor = mock_health_monitor

        app = create_test_app_extended()

        with TestClient(app) as client:
            yield client

        state.health_monitor = None

    def test_get_detailed_health(
        self, client: TestClient, mock_health_monitor
    ) -> None:
        """Test get detailed health status."""
        redis_health = ComponentHealth(
            name="redis",
            status=HealthStatus.HEALTHY,
            latency_ms=1.5,
        )
        db_health = ComponentHealth(
            name="database",
            status=HealthStatus.HEALTHY,
            latency_ms=5.0,
        )

        system_health = SystemHealth(
            overall=HealthStatus.HEALTHY,
            components={"redis": redis_health, "database": db_health},
            timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
        )

        mock_health_monitor.get_health.return_value = system_health

        response = client.get("/api/health/detailed")
        assert response.status_code == 200

        data = response.json()
        assert data["overall"] == "healthy"
        assert "redis" in data["components"]
        assert "database" in data["components"]

    def test_get_component_health_found(
        self, client: TestClient, mock_health_monitor
    ) -> None:
        """Test get component health when found."""
        component_health = ComponentHealth(
            name="redis",
            status=HealthStatus.HEALTHY,
            latency_ms=1.5,
        )
        mock_health_monitor.get_component_health.return_value = component_health

        response = client.get("/api/health/components/redis")
        assert response.status_code == 200

        data = response.json()
        assert data["name"] == "redis"
        assert data["status"] == "healthy"

    def test_get_component_health_not_found(
        self, client: TestClient, mock_health_monitor
    ) -> None:
        """Test get component health when not found."""
        mock_health_monitor.get_component_health.return_value = None

        response = client.get("/api/health/components/unknown")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "unknown"
        assert "not monitored" in data["error"]


class TestStrategiesEndpoint:
    """Tests for strategies API endpoints."""

    @pytest.fixture
    def strategies_config(self) -> StrategiesConfig:
        """Create strategies config for testing."""
        return StrategiesConfig(
            bar_stream="stream:bars:1m:us",
            consumer_group="test-strategies",
            enabled=[
                StrategyInstanceConfig(
                    type="momentum",
                    id="momentum_01",
                    enabled=True,
                    config={"rsi_oversold": 40},
                ),
                StrategyInstanceConfig(
                    type="mean_reversion",
                    id="mean_rev_01",
                    enabled=True,
                    config={"std_multiplier": 2.0},
                ),
            ],
        )

    @pytest.fixture
    def mock_state_repo(self) -> MagicMock:
        """Create a mock strategy state repository."""
        repo = AsyncMock()
        repo.get_all.return_value = []
        repo.get.return_value = None
        repo.set_state.return_value = StrategyState(
            strategy_id="momentum_01",
            enabled=True,
            updated_at=datetime.now(timezone.utc),
        )
        return repo

    @pytest.fixture
    def mock_control(self) -> MagicMock:
        """Create a mock strategy control publisher."""
        control = AsyncMock()
        control.enable.return_value = 1
        control.disable.return_value = 1
        return control

    @pytest.fixture
    def mock_position_repo(self) -> MagicMock:
        """Create a mock position repository."""
        repo = AsyncMock()
        repo.get_open_positions.return_value = []
        return repo

    @pytest.fixture
    def mock_order_repo(self) -> MagicMock:
        """Create a mock order repository."""
        repo = AsyncMock()
        repo.get_daily_realized_pnl.return_value = Decimal("0")
        repo.get_by_strategy.return_value = []
        repo.get_recent_fills.return_value = []
        repo.get_fills_chronological.return_value = []
        return repo

    @pytest.fixture
    def client(
        self,
        strategies_config,
        mock_state_repo,
        mock_control,
        mock_position_repo,
        mock_order_repo,
    ) -> TestClient:
        """Create test client with mocked dependencies."""
        state.strategies_config = strategies_config
        state.strategy_state_repo = mock_state_repo
        state.strategy_control = mock_control
        state.position_repo = mock_position_repo
        state.order_repo = mock_order_repo

        app = create_test_app_extended()

        with TestClient(app) as client:
            yield client

        state.strategies_config = None
        state.strategy_state_repo = None
        state.strategy_control = None
        state.position_repo = None
        state.order_repo = None

    def test_list_strategies(self, client: TestClient) -> None:
        """Test list strategies."""
        response = client.get("/api/strategies")
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 2
        assert data[0]["strategy_id"] == "momentum_01"
        assert data[0]["type"] == "momentum"
        assert data[1]["strategy_id"] == "mean_rev_01"

    def test_list_strategies_uses_persisted_state(
        self, client: TestClient, mock_state_repo
    ) -> None:
        """Test list strategies uses persisted enabled state."""
        mock_state_repo.get_all.return_value = [
            StrategyState(
                strategy_id="momentum_01",
                enabled=False,
                updated_at=datetime.now(timezone.utc),
            )
        ]

        response = client.get("/api/strategies")
        assert response.status_code == 200

        data = response.json()
        momentum = next(s for s in data if s["strategy_id"] == "momentum_01")
        assert momentum["enabled"] is False

    def test_get_strategy_detail(self, client: TestClient) -> None:
        """Test get strategy detail."""
        response = client.get("/api/strategies/momentum_01")
        assert response.status_code == 200

        data = response.json()
        assert data["strategy_id"] == "momentum_01"
        assert data["type"] == "momentum"
        assert "config" in data
        assert "positions" in data
        assert "recent_orders" in data

    def test_get_strategy_detail_not_found(self, client: TestClient) -> None:
        """Test get strategy detail for unknown strategy."""
        response = client.get("/api/strategies/unknown")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"]

    def test_enable_strategy(
        self, client: TestClient, mock_state_repo, mock_control
    ) -> None:
        """Test enable strategy."""
        response = client.post("/api/strategies/momentum_01/enable")
        assert response.status_code == 200

        data = response.json()
        assert data["enabled"] is True

        mock_state_repo.set_state.assert_called_once_with("momentum_01", enabled=True)
        mock_control.enable.assert_called_once_with("momentum_01")

    def test_enable_strategy_not_found(self, client: TestClient) -> None:
        """Test enable unknown strategy returns 404."""
        response = client.post("/api/strategies/unknown/enable")
        assert response.status_code == 404

    def test_disable_strategy(
        self, client: TestClient, mock_state_repo, mock_control
    ) -> None:
        """Test disable strategy."""
        response = client.post("/api/strategies/momentum_01/disable")
        assert response.status_code == 200

        data = response.json()
        assert data["enabled"] is False

        mock_state_repo.set_state.assert_called_once_with("momentum_01", enabled=False)
        mock_control.disable.assert_called_once_with("momentum_01")

    def test_disable_strategy_not_found(self, client: TestClient) -> None:
        """Test disable unknown strategy returns 404."""
        response = client.post("/api/strategies/unknown/disable")
        assert response.status_code == 404

    def test_get_strategy_performance_no_trades(
        self, client: TestClient, mock_order_repo
    ) -> None:
        """Test get strategy performance with no trades."""
        mock_order_repo.get_fills_chronological.return_value = []

        response = client.get("/api/strategies/momentum_01/performance")
        assert response.status_code == 200

        data = response.json()
        assert data["strategy_id"] == "momentum_01"
        assert data["trade_count"] == 0
        assert data["total_pnl"] == "0"

    def test_get_strategy_performance_not_found(self, client: TestClient) -> None:
        """Test get performance for unknown strategy."""
        response = client.get("/api/strategies/unknown/performance")
        assert response.status_code == 404
