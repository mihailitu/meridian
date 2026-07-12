"""Unit tests for gateway and discovery API endpoints."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from axtrade.api.routes import discovery, gateway
from axtrade.discovery import DiscoveredSymbol, DiscoveryService


def create_test_app() -> FastAPI:
    """Create a test app with gateway and discovery routes."""
    app = FastAPI(title="axtrade API Test Gateway Discovery")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(gateway.router, prefix="/api", tags=["gateway"])
    app.include_router(discovery.router, prefix="/api", tags=["discovery"])

    return app


class TestGatewayStatusEndpoint:
    """Tests for gateway status API endpoints."""

    @pytest.fixture
    def client(self) -> TestClient:
        """Create test client."""
        app = create_test_app()
        with TestClient(app) as client:
            yield client

    def test_get_gateway_status(self, client: TestClient) -> None:
        """Test getting gateway status."""
        with patch("axtrade.api.routes.gateway.load_config") as mock_config:
            mock_cfg = MagicMock()
            mock_cfg.gateway.adapter = "mock"
            mock_config.return_value = mock_cfg

            response = client.get("/api/gateway/status")
            assert response.status_code == 200

            data = response.json()
            assert data["current_adapter"] == "mock"
            assert "available_adapters" in data
            assert "mock" in data["available_adapters"]
            assert "ibkr" in data["available_adapters"]
            assert "alpaca" in data["available_adapters"]
            assert "yahoo" in data["available_adapters"]

    def test_get_gateway_status_all_adapters(self, client: TestClient) -> None:
        """Test all expected adapters are available."""
        with patch("axtrade.api.routes.gateway.load_config") as mock_config:
            mock_cfg = MagicMock()
            mock_cfg.gateway.adapter = "alpaca"
            mock_config.return_value = mock_cfg

            response = client.get("/api/gateway/status")
            assert response.status_code == 200

            data = response.json()
            assert len(data["available_adapters"]) == 4

    def test_set_gateway_preference_valid(self, client: TestClient) -> None:
        """Test setting a valid gateway preference."""
        with patch("axtrade.api.routes.gateway.load_config") as mock_config:
            mock_cfg = MagicMock()
            mock_cfg.gateway.adapter = "mock"
            mock_config.return_value = mock_cfg

            response = client.post(
                "/api/gateway/preference",
                json={"adapter": "alpaca"},
            )
            assert response.status_code == 200

            data = response.json()
            assert data["preferred_adapter"] == "alpaca"
            assert data["requires_restart"] is True

    def test_set_gateway_preference_same_as_current(self, client: TestClient) -> None:
        """Test setting preference to current adapter."""
        with patch("axtrade.api.routes.gateway.load_config") as mock_config:
            mock_cfg = MagicMock()
            mock_cfg.gateway.adapter = "mock"
            mock_config.return_value = mock_cfg

            response = client.post(
                "/api/gateway/preference",
                json={"adapter": "mock"},
            )
            assert response.status_code == 200

            data = response.json()
            assert data["preferred_adapter"] == "mock"
            assert data["requires_restart"] is False

    def test_set_gateway_preference_does_not_write_config_file(
        self, client: TestClient
    ) -> None:
        """Setting a preference must not touch config/default.yaml (audit P1-7).

        The preference is in-memory for the server lifetime; the gateway
        module no longer has a config-path helper or opens the file at all.
        """
        assert not hasattr(gateway, "_get_config_path")

        config_path = (
            Path(__file__).resolve().parents[2] / "config" / "default.yaml"
        )
        before_mtime = config_path.stat().st_mtime
        before_content = config_path.read_bytes()

        with patch("axtrade.api.routes.gateway.load_config") as mock_config:
            mock_cfg = MagicMock()
            mock_cfg.gateway.adapter = "mock"
            mock_config.return_value = mock_cfg

            response = client.post(
                "/api/gateway/preference",
                json={"adapter": "alpaca"},
            )
            assert response.status_code == 200

        assert config_path.stat().st_mtime == before_mtime
        assert config_path.read_bytes() == before_content

    def test_set_gateway_preference_invalid(self, client: TestClient) -> None:
        """Test setting an invalid gateway preference."""
        response = client.post(
            "/api/gateway/preference",
            json={"adapter": "invalid_adapter"},
        )
        assert response.status_code == 400
        assert "Invalid adapter" in response.json()["detail"]


class TestDiscoverySymbolsEndpoint:
    """Tests for discovery symbols API endpoints."""

    @pytest.fixture
    def mock_discovery_service(self) -> MagicMock:
        """Create a mock discovery service."""
        service = MagicMock(spec=DiscoveryService)
        service.get_discovered.return_value = []
        service.add_manual_symbol.return_value = DiscoveredSymbol(
            symbol="TSLA",
            source="manual",
            score=0.0,
            price=250.00,
        )
        return service

    @pytest.fixture
    def client(self, mock_discovery_service) -> TestClient:
        """Create test client with mocked discovery service."""
        app = create_test_app()

        # Override the FastAPI dependency
        app.dependency_overrides[discovery.get_discovery_service] = lambda: mock_discovery_service

        with TestClient(app) as client:
            yield client

        # Clean up
        app.dependency_overrides.clear()

    def test_add_symbol(self, client: TestClient, mock_discovery_service) -> None:
        """Test adding a symbol manually."""
        response = client.post(
            "/api/discovery/symbols",
            json={"symbol": "TSLA", "price": 250.00},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["symbol"] == "TSLA"
        assert data["source"] == "manual"
        assert data["score"] == 0.0
        assert data["price"] == 250.00

        mock_discovery_service.add_manual_symbol.assert_called_once_with(
            symbol="TSLA",
            price=250.00,
            notes=None,
        )

    def test_add_symbol_with_notes(
        self, client: TestClient, mock_discovery_service
    ) -> None:
        """Test adding a symbol with notes."""
        mock_discovery_service.add_manual_symbol.return_value = DiscoveredSymbol(
            symbol="AAPL",
            source="manual",
            score=0.0,
            metadata={"notes": "Earnings play"},
        )

        response = client.post(
            "/api/discovery/symbols",
            json={"symbol": "AAPL", "notes": "Earnings play"},
        )
        assert response.status_code == 200

        mock_discovery_service.add_manual_symbol.assert_called_once_with(
            symbol="AAPL",
            price=None,
            notes="Earnings play",
        )

    def test_add_symbol_minimal(
        self, client: TestClient, mock_discovery_service
    ) -> None:
        """Test adding a symbol with just the symbol name."""
        mock_discovery_service.add_manual_symbol.return_value = DiscoveredSymbol(
            symbol="NVDA",
            source="manual",
            score=0.0,
        )

        response = client.post(
            "/api/discovery/symbols",
            json={"symbol": "NVDA"},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["symbol"] == "NVDA"
        assert data["source"] == "manual"

    def test_add_symbol_missing_symbol(self, client: TestClient) -> None:
        """Test adding a symbol without required symbol field."""
        response = client.post(
            "/api/discovery/symbols",
            json={"price": 100.00},
        )
        assert response.status_code == 422  # Validation error

    def test_get_discovered_symbols(
        self, client: TestClient, mock_discovery_service
    ) -> None:
        """Test getting discovered symbols."""
        mock_discovery_service.get_discovered.return_value = [
            DiscoveredSymbol(
                symbol="AAPL",
                source="manual",
                score=0.0,
                price=185.00,
            ),
            DiscoveredSymbol(
                symbol="TSLA",
                source="momentum",
                score=0.8,
                price=250.00,
            ),
        ]

        response = client.get("/api/discovery/symbols")
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 2
        assert data[0]["symbol"] == "AAPL"
        assert data[1]["symbol"] == "TSLA"

    def test_clear_discovered_symbols(
        self, client: TestClient, mock_discovery_service
    ) -> None:
        """Test clearing discovered symbols."""
        response = client.delete("/api/discovery/symbols")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "ok"
        mock_discovery_service.clear_discovered.assert_called_once()
