"""Unit tests for API endpoints."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from axtrade.api.dependencies import state
from axtrade.api.routes import orders, pnl, positions
from axtrade.common import APIConfig, Config, DatabaseConfig
from axtrade.oms.types import Fill, Order, OrderSide, OrderStatus, OrderType, Position


@pytest.fixture
def mock_config() -> Config:
    """Create a minimal config for testing."""
    config = Config()
    config.api = APIConfig(host="127.0.0.1", port=8000, cors_origins=["*"])
    config.database = DatabaseConfig()
    return config


@pytest.fixture
def mock_position_repo() -> MagicMock:
    """Create a mock position repository."""
    repo = MagicMock()
    repo.get_open_positions = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_order_repo() -> MagicMock:
    """Create a mock order repository."""
    repo = MagicMock()
    repo.get_recent_orders = AsyncMock(return_value=[])
    repo.get = AsyncMock(return_value=None)
    repo.get_fills_for_order = AsyncMock(return_value=[])
    repo.get_recent_fills = AsyncMock(return_value=[])
    repo.get_daily_realized_pnl = AsyncMock(return_value=Decimal("0"))
    return repo


def create_test_app() -> FastAPI:
    """Create a test app without lifespan."""
    app = FastAPI(title="axtrade API Test")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(positions.router, prefix="/api", tags=["positions"])
    app.include_router(orders.router, prefix="/api", tags=["orders"])
    app.include_router(pnl.router, prefix="/api", tags=["pnl"])

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


@pytest.fixture
def client(mock_position_repo, mock_order_repo) -> TestClient:
    """Create test client with mocked dependencies."""
    # Set up mock state
    state.position_repo = mock_position_repo
    state.order_repo = mock_order_repo

    app = create_test_app()

    with TestClient(app) as client:
        yield client

    # Clean up
    state.position_repo = None
    state.order_repo = None


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_returns_ok(self, client: TestClient) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestPositionsEndpoint:
    """Tests for positions endpoints."""

    def test_get_positions_empty(self, client: TestClient) -> None:
        response = client.get("/api/positions")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_positions_returns_data(
        self, client: TestClient, mock_position_repo
    ) -> None:
        mock_position_repo.get_open_positions.return_value = [
            Position(
                strategy_id="test",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("185.50"),
                current_price=Decimal("186.00"),
                unrealized_pnl=Decimal("50.00"),
            )
        ]

        response = client.get("/api/positions")
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 1
        assert data[0]["symbol"] == "AAPL"
        assert data[0]["side"] == "long"
        assert data[0]["quantity"] == "100"

    def test_get_positions_with_strategy_filter(
        self, client: TestClient, mock_position_repo
    ) -> None:
        response = client.get("/api/positions?strategy_id=momentum_01")
        assert response.status_code == 200
        mock_position_repo.get_open_positions.assert_called_with("momentum_01")

    def test_get_position_not_found(self, client: TestClient) -> None:
        response = client.get("/api/positions/INVALID")
        assert response.status_code == 404


class TestOrdersEndpoint:
    """Tests for orders endpoints."""

    def test_get_orders_empty(self, client: TestClient) -> None:
        response = client.get("/api/orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_orders_returns_data(
        self, client: TestClient, mock_order_repo
    ) -> None:
        order_id = uuid4()
        now = datetime.now(timezone.utc)
        mock_order_repo.get_recent_orders.return_value = [
            Order(
                id=order_id,
                strategy_id="test",
                symbol="AAPL",
                side=OrderSide.BUY,
                quantity=Decimal("100"),
                order_type=OrderType.MARKET,
                status=OrderStatus.FILLED,
                filled_quantity=Decimal("100"),
                avg_fill_price=Decimal("185.50"),
                created_at=now,
                updated_at=now,
            )
        ]

        response = client.get("/api/orders")
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == str(order_id)
        assert data[0]["symbol"] == "AAPL"
        assert data[0]["side"] == "buy"
        assert data[0]["status"] == "filled"

    def test_get_orders_with_filters(
        self, client: TestClient, mock_order_repo
    ) -> None:
        response = client.get("/api/orders?strategy_id=test&status=filled&limit=10")
        assert response.status_code == 200
        mock_order_repo.get_recent_orders.assert_called_with("test", "filled", 10)

    def test_get_order_by_id(self, client: TestClient, mock_order_repo) -> None:
        order_id = uuid4()
        now = datetime.now(timezone.utc)
        mock_order_repo.get.return_value = Order(
            id=order_id,
            strategy_id="test",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            created_at=now,
            updated_at=now,
        )

        response = client.get(f"/api/orders/{order_id}")
        assert response.status_code == 200
        assert response.json()["id"] == str(order_id)

    def test_get_order_not_found(self, client: TestClient) -> None:
        response = client.get(f"/api/orders/{uuid4()}")
        assert response.status_code == 404

    def test_get_order_invalid_id(self, client: TestClient) -> None:
        response = client.get("/api/orders/invalid-uuid")
        assert response.status_code == 400


class TestFillsEndpoint:
    """Tests for fills endpoints."""

    def test_get_fills_empty(self, client: TestClient) -> None:
        response = client.get("/api/fills")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_fills_returns_data(
        self, client: TestClient, mock_order_repo
    ) -> None:
        fill_id = uuid4()
        order_id = uuid4()
        now = datetime.now(timezone.utc)
        mock_order_repo.get_recent_fills.return_value = [
            Fill(
                id=fill_id,
                order_id=order_id,
                strategy_id="test",
                symbol="AAPL",
                side=OrderSide.BUY,
                quantity=Decimal("100"),
                price=Decimal("185.50"),
                commission=Decimal("1.00"),
                filled_at=now,
            )
        ]

        response = client.get("/api/fills")
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == str(fill_id)
        assert data[0]["symbol"] == "AAPL"


class TestPnLEndpoint:
    """Tests for P&L endpoints."""

    def test_get_pnl_summary(self, client: TestClient, mock_order_repo) -> None:
        mock_order_repo.get_daily_realized_pnl.return_value = Decimal("150.00")

        response = client.get("/api/pnl/summary")
        assert response.status_code == 200

        data = response.json()
        assert data["daily_realized"] == "150.00"
        assert data["daily_unrealized"] == "0"
        assert data["daily_total"] == "150.00"

    def test_get_pnl_summary_with_positions(
        self, client: TestClient, mock_order_repo, mock_position_repo
    ) -> None:
        mock_order_repo.get_daily_realized_pnl.return_value = Decimal("100.00")
        mock_position_repo.get_open_positions.return_value = [
            Position(
                strategy_id="test",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("185.00"),
                unrealized_pnl=Decimal("50.00"),
                realized_pnl=Decimal("200.00"),
            )
        ]

        response = client.get("/api/pnl/summary")
        assert response.status_code == 200

        data = response.json()
        assert data["daily_realized"] == "100.00"
        assert data["daily_unrealized"] == "50.00"
        assert data["daily_total"] == "150.00"
        assert data["cumulative_realized"] == "300.00"  # 200 + 100
