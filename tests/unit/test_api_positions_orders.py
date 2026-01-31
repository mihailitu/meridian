"""Unit tests for positions, orders, and fills API endpoints."""

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
from axtrade.oms.types import Fill, Order, OrderSide, OrderStatus, OrderType, Position


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

    return app


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


@pytest.fixture
def client(mock_position_repo, mock_order_repo) -> TestClient:
    """Create test client with mocked dependencies."""
    state.position_repo = mock_position_repo
    state.order_repo = mock_order_repo

    app = create_test_app()

    with TestClient(app) as client:
        yield client

    state.position_repo = None
    state.order_repo = None


class TestGetPositions:
    """Tests for GET /api/positions endpoint."""

    def test_get_positions_empty(self, client: TestClient) -> None:
        """Test get positions returns empty list when no positions."""
        response = client.get("/api/positions")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_positions_returns_data(
        self, client: TestClient, mock_position_repo
    ) -> None:
        """Test get positions returns position data."""
        mock_position_repo.get_open_positions.return_value = [
            Position(
                strategy_id="momentum_01",
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
        assert data[0]["unrealized_pnl"] == "50.00"

    def test_get_positions_multiple(
        self, client: TestClient, mock_position_repo
    ) -> None:
        """Test get positions returns multiple positions."""
        mock_position_repo.get_open_positions.return_value = [
            Position(
                strategy_id="momentum_01",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("185.50"),
            ),
            Position(
                strategy_id="mean_rev_01",
                symbol="MSFT",
                side="short",
                quantity=Decimal("50"),
                avg_entry_price=Decimal("420.00"),
            ),
        ]

        response = client.get("/api/positions")
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 2
        assert data[0]["symbol"] == "AAPL"
        assert data[1]["symbol"] == "MSFT"

    def test_get_positions_with_strategy_filter(
        self, client: TestClient, mock_position_repo
    ) -> None:
        """Test get positions filters by strategy_id."""
        response = client.get("/api/positions?strategy_id=momentum_01")
        assert response.status_code == 200
        mock_position_repo.get_open_positions.assert_called_with("momentum_01")


class TestGetPositionBySymbol:
    """Tests for GET /api/positions/{symbol} endpoint."""

    def test_get_position_found(
        self, client: TestClient, mock_position_repo
    ) -> None:
        """Test get position by symbol returns data when found."""
        mock_position_repo.get_open_positions.return_value = [
            Position(
                strategy_id="momentum_01",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("185.50"),
                current_price=Decimal("186.00"),
                unrealized_pnl=Decimal("50.00"),
            )
        ]

        response = client.get("/api/positions/AAPL")
        assert response.status_code == 200

        data = response.json()
        assert data["symbol"] == "AAPL"
        assert data["quantity"] == "100"

    def test_get_position_not_found(self, client: TestClient) -> None:
        """Test get position by symbol returns 404 when not found."""
        response = client.get("/api/positions/INVALID")
        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_get_position_with_strategy_filter(
        self, client: TestClient, mock_position_repo
    ) -> None:
        """Test get position by symbol with strategy filter."""
        mock_position_repo.get_open_positions.return_value = [
            Position(
                strategy_id="momentum_01",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("185.50"),
            )
        ]

        response = client.get("/api/positions/AAPL?strategy_id=momentum_01")
        assert response.status_code == 200
        mock_position_repo.get_open_positions.assert_called_with("momentum_01")


class TestGetOrders:
    """Tests for GET /api/orders endpoint."""

    def test_get_orders_empty(self, client: TestClient) -> None:
        """Test get orders returns empty list when no orders."""
        response = client.get("/api/orders")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_orders_returns_data(
        self, client: TestClient, mock_order_repo
    ) -> None:
        """Test get orders returns order data."""
        order_id = uuid4()
        now = datetime.now(timezone.utc)
        mock_order_repo.get_recent_orders.return_value = [
            Order(
                id=order_id,
                strategy_id="momentum_01",
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
        """Test get orders with query filters."""
        response = client.get("/api/orders?strategy_id=test&status=filled&limit=10")
        assert response.status_code == 200
        mock_order_repo.get_recent_orders.assert_called_with("test", "filled", 10)

    def test_get_orders_pending_status(
        self, client: TestClient, mock_order_repo
    ) -> None:
        """Test get orders filtered by pending status."""
        order_id = uuid4()
        now = datetime.now(timezone.utc)
        mock_order_repo.get_recent_orders.return_value = [
            Order(
                id=order_id,
                strategy_id="momentum_01",
                symbol="AAPL",
                side=OrderSide.BUY,
                quantity=Decimal("100"),
                order_type=OrderType.LIMIT,
                status=OrderStatus.PENDING,
                limit_price=Decimal("185.00"),
                created_at=now,
                updated_at=now,
            )
        ]

        response = client.get("/api/orders?status=pending")
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] == "pending"
        assert data[0]["order_type"] == "limit"


class TestGetOrderById:
    """Tests for GET /api/orders/{order_id} endpoint."""

    def test_get_order_found(self, client: TestClient, mock_order_repo) -> None:
        """Test get order by ID returns data when found."""
        order_id = uuid4()
        now = datetime.now(timezone.utc)
        mock_order_repo.get.return_value = Order(
            id=order_id,
            strategy_id="momentum_01",
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
        """Test get order by ID returns 404 when not found."""
        response = client.get(f"/api/orders/{uuid4()}")
        assert response.status_code == 404

    def test_get_order_invalid_id(self, client: TestClient) -> None:
        """Test get order with invalid UUID returns 400."""
        response = client.get("/api/orders/invalid-uuid")
        assert response.status_code == 400
        assert "Invalid order ID" in response.json()["detail"]


class TestGetFills:
    """Tests for GET /api/fills endpoint."""

    def test_get_fills_empty(self, client: TestClient) -> None:
        """Test get fills returns empty list when no fills."""
        response = client.get("/api/fills")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_fills_returns_data(
        self, client: TestClient, mock_order_repo
    ) -> None:
        """Test get fills returns fill data."""
        fill_id = uuid4()
        order_id = uuid4()
        now = datetime.now(timezone.utc)
        mock_order_repo.get_recent_fills.return_value = [
            Fill(
                id=fill_id,
                order_id=order_id,
                strategy_id="momentum_01",
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
        assert data[0]["price"] == "185.50"

    def test_get_fills_with_strategy_filter(
        self, client: TestClient, mock_order_repo
    ) -> None:
        """Test get fills with strategy filter."""
        response = client.get("/api/fills?strategy_id=momentum_01&limit=25")
        assert response.status_code == 200
        mock_order_repo.get_recent_fills.assert_called_with("momentum_01", 25)


class TestGetPnLSummary:
    """Tests for GET /api/pnl/summary endpoint."""

    def test_get_pnl_summary_no_positions(
        self, client: TestClient, mock_order_repo
    ) -> None:
        """Test get P&L summary with no positions."""
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
        """Test get P&L summary with open positions."""
        mock_order_repo.get_daily_realized_pnl.return_value = Decimal("100.00")
        mock_position_repo.get_open_positions.return_value = [
            Position(
                strategy_id="momentum_01",
                symbol="AAPL",
                side="long",
                quantity=Decimal("100"),
                avg_entry_price=Decimal("185.00"),
                unrealized_pnl=Decimal("50.00"),
                realized_pnl=Decimal("200.00"),
            ),
            Position(
                strategy_id="mean_rev_01",
                symbol="MSFT",
                side="long",
                quantity=Decimal("50"),
                avg_entry_price=Decimal("420.00"),
                unrealized_pnl=Decimal("-30.00"),
                realized_pnl=Decimal("100.00"),
            ),
        ]

        response = client.get("/api/pnl/summary")
        assert response.status_code == 200

        data = response.json()
        assert data["daily_realized"] == "100.00"
        assert data["daily_unrealized"] == "20.00"  # 50 - 30
        assert data["daily_total"] == "120.00"  # 100 + 20
        assert data["cumulative_realized"] == "400.00"  # 200 + 100 + 100

    def test_get_pnl_summary_with_strategy_filter(
        self, client: TestClient, mock_order_repo, mock_position_repo
    ) -> None:
        """Test get P&L summary filters by strategy."""
        response = client.get("/api/pnl/summary?strategy_id=momentum_01")
        assert response.status_code == 200
        mock_order_repo.get_daily_realized_pnl.assert_called_with("momentum_01")
        mock_position_repo.get_open_positions.assert_called_with("momentum_01")
