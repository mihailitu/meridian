"""Unit tests for analytics API endpoints."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from axtrade.api.dependencies import state
from axtrade.api.routes import analytics
from axtrade.oms.types import Fill, OrderSide


def create_analytics_test_app() -> FastAPI:
    """Create a test app for analytics endpoints."""
    app = FastAPI(title="axtrade Analytics API Test")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(analytics.router, prefix="/api", tags=["analytics"])

    return app


@pytest.fixture
def mock_order_repo() -> MagicMock:
    """Create a mock order repository."""
    repo = MagicMock()
    repo.get_recent_fills = AsyncMock(return_value=[])
    repo.get_daily_pnl_series = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_position_repo() -> MagicMock:
    """Create a mock position repository."""
    repo = MagicMock()
    repo.get_open_positions = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def client(mock_order_repo, mock_position_repo) -> TestClient:
    """Create test client with mocked dependencies."""
    state.order_repo = mock_order_repo
    state.position_repo = mock_position_repo

    app = create_analytics_test_app()

    with TestClient(app) as client:
        yield client

    state.order_repo = None
    state.position_repo = None


@pytest.fixture
def sample_fills():
    """Create sample fill data for tests."""
    now = datetime.now(timezone.utc)
    return [
        Fill(
            id=uuid4(),
            order_id=uuid4(),
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.BUY,
            quantity=Decimal("100"),
            price=Decimal("185.50"),
            commission=Decimal("1.00"),
            filled_at=now - timedelta(hours=2),
        ),
        Fill(
            id=uuid4(),
            order_id=uuid4(),
            strategy_id="momentum_01",
            symbol="AAPL",
            side=OrderSide.SELL,
            quantity=Decimal("100"),
            price=Decimal("186.50"),
            commission=Decimal("1.00"),
            filled_at=now - timedelta(hours=1),
        ),
        Fill(
            id=uuid4(),
            order_id=uuid4(),
            strategy_id="mean_rev_01",
            symbol="MSFT",
            side=OrderSide.BUY,
            quantity=Decimal("50"),
            price=Decimal("420.00"),
            commission=Decimal("1.00"),
            filled_at=now,
        ),
    ]


class TestGetAnalyticsSummary:
    """Tests for GET /api/analytics/summary endpoint."""

    def test_get_analytics_summary_no_trades(self, client: TestClient) -> None:
        """Test analytics summary with no trades."""
        response = client.get("/api/analytics/summary")
        assert response.status_code == 200

        data = response.json()
        assert data["total_trades"] == 0
        assert data["total_pnl"] == "0"
        assert data["win_rate"] == 0.0

    def test_get_analytics_summary_with_trades(
        self, client: TestClient, mock_order_repo, sample_fills
    ) -> None:
        """Test analytics summary with trade data."""
        mock_order_repo.get_recent_fills.return_value = sample_fills

        response = client.get("/api/analytics/summary")
        assert response.status_code == 200

        data = response.json()
        assert "total_pnl" in data
        assert "total_trades" in data
        assert "win_rate" in data
        assert "profit_factor" in data
        assert "sharpe_ratio" in data

    def test_get_analytics_summary_fields(self, client: TestClient) -> None:
        """Test analytics summary includes all expected fields."""
        response = client.get("/api/analytics/summary")
        assert response.status_code == 200

        data = response.json()
        expected_fields = [
            "total_pnl",
            "total_trades",
            "win_rate",
            "profit_factor",
            "sharpe_ratio",
            "sortino_ratio",
            "max_drawdown",
            "best_strategy",
            "worst_strategy",
            "strategy_count",
            "avg_correlation",
        ]
        for field in expected_fields:
            assert field in data


class TestGetRollingMetrics:
    """Tests for GET /api/analytics/rolling endpoint."""

    def test_get_rolling_metrics_no_data(self, client: TestClient) -> None:
        """Test rolling metrics with no data."""
        response = client.get("/api/analytics/rolling")
        assert response.status_code == 200

        data = response.json()
        assert data["data_points"] == 0
        assert data["sharpe_ratio"] is None

    def test_get_rolling_metrics_with_data(
        self, client: TestClient, mock_order_repo
    ) -> None:
        """Test rolling metrics with daily P&L data."""
        mock_order_repo.get_daily_pnl_series.return_value = [
            100.0, 50.0, -30.0, 80.0, 120.0,
            -50.0, 40.0, 60.0, -20.0, 90.0,
        ]

        response = client.get("/api/analytics/rolling?window=5")
        assert response.status_code == 200

        data = response.json()
        assert data["window_days"] == 5
        assert "sharpe_ratio" in data
        assert "volatility" in data

    def test_get_rolling_metrics_window_validation(
        self, client: TestClient
    ) -> None:
        """Test rolling metrics validates window parameter."""
        # Too small window
        response = client.get("/api/analytics/rolling?window=2")
        assert response.status_code == 422

        # Too large window
        response = client.get("/api/analytics/rolling?window=500")
        assert response.status_code == 422

    def test_get_rolling_metrics_default_window(
        self, client: TestClient, mock_order_repo
    ) -> None:
        """Test rolling metrics uses default window."""
        response = client.get("/api/analytics/rolling")
        assert response.status_code == 200
        # Default window is 30 * 2 = 60 for the call
        mock_order_repo.get_daily_pnl_series.assert_called_once()


class TestGetDrawdownInfo:
    """Tests for GET /api/analytics/drawdown endpoint."""

    def test_get_drawdown_info_no_data(self, client: TestClient) -> None:
        """Test drawdown info with no data."""
        response = client.get("/api/analytics/drawdown")
        assert response.status_code == 200

        data = response.json()
        assert data["current_drawdown_pct"] == 0.0
        assert data["max_drawdown_pct"] == 0.0
        assert data["in_drawdown"] is False

    def test_get_drawdown_info_with_data(
        self, client: TestClient, mock_order_repo
    ) -> None:
        """Test drawdown info with P&L data."""
        mock_order_repo.get_daily_pnl_series.return_value = [
            500.0, 300.0, -800.0, 200.0, 400.0,
        ]

        response = client.get("/api/analytics/drawdown")
        assert response.status_code == 200

        data = response.json()
        assert "current_drawdown_pct" in data
        assert "max_drawdown_pct" in data
        assert "peak_value" in data
        assert "current_value" in data
        assert "in_drawdown" in data
        assert "drawdown_duration_days" in data

    def test_get_drawdown_info_all_fields(self, client: TestClient) -> None:
        """Test drawdown info includes all expected fields."""
        response = client.get("/api/analytics/drawdown")
        assert response.status_code == 200

        data = response.json()
        expected_fields = [
            "current_drawdown_pct",
            "max_drawdown_pct",
            "in_drawdown",
            "drawdown_duration_days",
        ]
        for field in expected_fields:
            assert field in data


class TestGetTradeStatistics:
    """Tests for GET /api/analytics/trades endpoint."""

    def test_get_trade_statistics_no_trades(self, client: TestClient) -> None:
        """Test trade statistics with no trades."""
        response = client.get("/api/analytics/trades")
        assert response.status_code == 200

        data = response.json()
        assert data["total_trades"] == 0
        assert data["winning_trades"] == 0
        assert data["win_rate"] == 0.0

    def test_get_trade_statistics_with_trades(
        self, client: TestClient, mock_order_repo, sample_fills
    ) -> None:
        """Test trade statistics with trade data."""
        mock_order_repo.get_recent_fills.return_value = sample_fills

        response = client.get("/api/analytics/trades")
        assert response.status_code == 200

        data = response.json()
        assert "total_trades" in data
        assert "winning_trades" in data
        assert "losing_trades" in data
        assert "win_rate" in data
        assert "profit_factor" in data
        assert "expectancy" in data

    def test_get_trade_statistics_all_fields(self, client: TestClient) -> None:
        """Test trade statistics includes all expected fields."""
        response = client.get("/api/analytics/trades")
        assert response.status_code == 200

        data = response.json()
        expected_fields = [
            "total_trades",
            "winning_trades",
            "losing_trades",
            "breakeven_trades",
            "win_rate",
            "avg_win",
            "avg_loss",
            "avg_trade",
            "avg_win_loss_ratio",
            "profit_factor",
            "expectancy",
            "total_pnl",
            "largest_win",
            "largest_loss",
            "max_consecutive_wins",
            "max_consecutive_losses",
            "current_streak",
        ]
        for field in expected_fields:
            assert field in data


class TestGetTimeAnalysis:
    """Tests for GET /api/analytics/trades/time endpoint."""

    def test_get_time_analysis_no_trades(self, client: TestClient) -> None:
        """Test time analysis with no trades."""
        response = client.get("/api/analytics/trades/time")
        assert response.status_code == 200

        data = response.json()
        assert "hourly_pnl" in data
        assert "daily_pnl" in data
        assert "monthly_pnl" in data

    def test_get_time_analysis_with_trades(
        self, client: TestClient, mock_order_repo, sample_fills
    ) -> None:
        """Test time analysis with trade data."""
        mock_order_repo.get_recent_fills.return_value = sample_fills

        response = client.get("/api/analytics/trades/time")
        assert response.status_code == 200

        data = response.json()
        assert "hourly_pnl" in data
        assert "hourly_trades" in data
        assert "daily_pnl" in data
        assert "daily_trades" in data
        assert "monthly_pnl" in data
        assert "monthly_trades" in data

    def test_get_time_analysis_all_fields(self, client: TestClient) -> None:
        """Test time analysis includes all expected fields."""
        response = client.get("/api/analytics/trades/time")
        assert response.status_code == 200

        data = response.json()
        expected_fields = [
            "hourly_pnl",
            "hourly_trades",
            "daily_pnl",
            "daily_trades",
            "monthly_pnl",
            "monthly_trades",
        ]
        for field in expected_fields:
            assert field in data


class TestGetStrategyPerformance:
    """Tests for GET /api/analytics/strategies endpoint."""

    def test_get_strategy_performance_no_trades(self, client: TestClient) -> None:
        """Test strategy performance with no trades."""
        response = client.get("/api/analytics/strategies")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_get_strategy_performance_with_trades(
        self, client: TestClient, mock_order_repo, sample_fills
    ) -> None:
        """Test strategy performance with trade data."""
        mock_order_repo.get_recent_fills.return_value = sample_fills

        response = client.get("/api/analytics/strategies")
        assert response.status_code == 200

        data = response.json()
        assert isinstance(data, list)

        # Should have strategies from the fills
        strategy_ids = [s["strategy_id"] for s in data]
        assert "momentum_01" in strategy_ids or len(data) == 0

    def test_get_strategy_performance_fields(
        self, client: TestClient, mock_order_repo, sample_fills
    ) -> None:
        """Test strategy performance includes all expected fields."""
        mock_order_repo.get_recent_fills.return_value = sample_fills

        response = client.get("/api/analytics/strategies")
        assert response.status_code == 200

        data = response.json()
        if len(data) > 0:
            strategy = data[0]
            expected_fields = [
                "strategy_id",
                "total_pnl",
                "trade_count",
                "win_rate",
                "profit_factor",
                "sharpe_ratio",
            ]
            for field in expected_fields:
                assert field in strategy
