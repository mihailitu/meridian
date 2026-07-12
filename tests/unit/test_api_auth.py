"""Unit tests for API key authentication (audit P0-5)."""

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from axtrade.api.dependencies import state
from axtrade.api.routes import alerts, gateway
from axtrade.common.config import load_config


def create_test_app() -> FastAPI:
    """Create a test app covering both a protected route and a GET route."""
    app = FastAPI(title="axtrade API Test Auth")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(alerts.router, prefix="/api", tags=["alerts"])
    app.include_router(gateway.router, prefix="/api", tags=["gateway"])

    return app


@pytest.fixture
def mock_alert_repo() -> MagicMock:
    """Create a mock alert repository so the protected route can succeed."""
    repo = MagicMock()
    repo.acknowledge = MagicMock(return_value=True)
    return repo


@pytest.fixture
def client(mock_alert_repo) -> TestClient:
    """Create a test client, resetting the shared api_key state afterwards."""
    state.alert_repo = mock_alert_repo

    app = create_test_app()
    with TestClient(app) as client:
        yield client

    # api/dependencies.state is a process-wide singleton shared by every
    # route module's test app; reset it so other test files aren't affected.
    state.alert_repo = None
    state.api_key = ""


class TestAuthDisabled:
    """When no api_key is configured, auth is a no-op."""

    def test_protected_route_not_401_when_no_key_configured(self, client: TestClient) -> None:
        state.api_key = ""

        response = client.post("/api/alerts/test-alert-1/acknowledge")

        assert response.status_code != 401


class TestAuthEnabled:
    """When an api_key is configured, the header is required and checked."""

    def test_missing_header_returns_401(self, client: TestClient) -> None:
        state.api_key = "secret-key"

        response = client.post("/api/alerts/test-alert-1/acknowledge")

        assert response.status_code == 401
        assert "Invalid or missing API key" in response.json()["detail"]

    def test_wrong_key_returns_401(self, client: TestClient) -> None:
        state.api_key = "secret-key"

        response = client.post(
            "/api/alerts/test-alert-1/acknowledge",
            headers={"X-API-Key": "wrong-key"},
        )

        assert response.status_code == 401

    def test_correct_key_not_401(self, client: TestClient) -> None:
        state.api_key = "secret-key"

        response = client.post(
            "/api/alerts/test-alert-1/acknowledge",
            headers={"X-API-Key": "secret-key"},
        )

        assert response.status_code != 401
        assert response.status_code == 200

    def test_get_route_works_without_header_when_key_configured(
        self, client: TestClient
    ) -> None:
        """GET routes are never protected — no header needed even with a key set."""
        state.api_key = "secret-key"

        with patch("axtrade.api.routes.gateway.load_config") as mock_config:
            mock_cfg = MagicMock()
            mock_cfg.gateway.adapter = "mock"
            mock_config.return_value = mock_cfg

            response = client.get("/api/gateway/status")

        assert response.status_code == 200


class TestConfigEnvVarPrecedence:
    """AXTRADE_API_KEY env var takes precedence over the yaml value."""

    def test_env_var_overrides_yaml(self, tmp_path, monkeypatch) -> None:
        config_path = tmp_path / "test_config.yaml"
        config_path.write_text(
            "api:\n"
            "  host: \"127.0.0.1\"\n"
            "  port: 8000\n"
            "  api_key: \"from-yaml\"\n"
        )

        monkeypatch.setenv("AXTRADE_API_KEY", "from-env")
        config = load_config(config_path)

        assert config.api.api_key == "from-env"

    def test_yaml_used_when_env_var_unset(self, tmp_path, monkeypatch) -> None:
        config_path = tmp_path / "test_config.yaml"
        config_path.write_text(
            "api:\n"
            "  host: \"127.0.0.1\"\n"
            "  port: 8000\n"
            "  api_key: \"from-yaml\"\n"
        )

        monkeypatch.delenv("AXTRADE_API_KEY", raising=False)
        config = load_config(config_path)

        assert config.api.api_key == "from-yaml"

    def test_default_host_is_loopback(self, tmp_path, monkeypatch) -> None:
        config_path = tmp_path / "test_config.yaml"
        config_path.write_text("api:\n  port: 8000\n")

        monkeypatch.delenv("AXTRADE_API_KEY", raising=False)
        config = load_config(config_path)

        assert config.api.host == "127.0.0.1"
        assert config.api.api_key == ""
