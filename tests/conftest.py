"""Test fixtures for axtrade."""

import pytest

from axtrade.common import (
    Config,
    DatabaseConfig,
    GatewayConfig,
    IndicatorConfig,
    MockConfig,
    RedisConfig,
    SymbolConfig,
)


@pytest.fixture
def mock_config():
    """Create a mock configuration for testing."""
    return MockConfig(
        tick_interval_ms=100,
        volatility=0.001,
    )


@pytest.fixture
def symbol_configs():
    """Create symbol configurations for testing."""
    return [
        SymbolConfig(symbol="AAPL", base_price=185.00),
        SymbolConfig(symbol="MSFT", base_price=420.00),
    ]


@pytest.fixture
def gateway_config(mock_config, symbol_configs):
    """Create gateway configuration for testing."""
    return GatewayConfig(
        adapter="mock",
        mock=mock_config,
        symbols=symbol_configs,
    )


@pytest.fixture
def redis_config():
    """Create Redis configuration for testing."""
    return RedisConfig(
        host="localhost",
        port=6379,
        stream_prefix="stream:ticks:test",
    )


@pytest.fixture
def database_config():
    """Create database configuration for testing."""
    return DatabaseConfig(
        host="localhost",
        port=5432,
        database="axtrade_test",
        user="axtrade",
        password="axtrade",
    )


@pytest.fixture
def indicator_config():
    """Create indicator configuration for testing."""
    return IndicatorConfig(
        sma_period=20,
        rsi_period=14,
    )


@pytest.fixture
def config(gateway_config, redis_config, database_config, indicator_config):
    """Create full configuration for testing."""
    return Config(
        gateway=gateway_config,
        redis=redis_config,
        database=database_config,
        indicators=indicator_config,
    )
