"""Configuration loading and management."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from .types import SymbolConfig


@dataclass
class MockConfig:
    """Mock adapter configuration."""

    tick_interval_ms: int = 500
    volatility: float = 0.001


@dataclass
class IBKRConfig:
    """IBKR adapter configuration."""

    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 1


@dataclass
class AlpacaConfig:
    """Alpaca adapter configuration."""

    api_key: str = ""
    secret_key: str = ""
    feed: str = "iex"  # "iex" (free) or "sip" (paid)
    paper: bool = True


@dataclass
class YahooConfig:
    """Yahoo Finance adapter configuration."""

    poll_interval_ms: int = 5000  # Polling interval in milliseconds


@dataclass
class GatewayConfig:
    """Gateway service configuration."""

    adapter: str = "mock"
    mock: MockConfig = field(default_factory=MockConfig)
    ibkr: IBKRConfig = field(default_factory=IBKRConfig)
    alpaca: AlpacaConfig = field(default_factory=AlpacaConfig)
    yahoo: YahooConfig = field(default_factory=YahooConfig)
    symbols: list[SymbolConfig] = field(default_factory=list)


@dataclass
class RedisConfig:
    """Redis configuration."""

    host: str = "localhost"
    port: int = 6379
    stream_prefix: str = "stream:ticks"


@dataclass
class AggregatorConfig:
    """Aggregator service configuration."""

    intervals: list[str] = field(default_factory=lambda: ["1m", "5m"])
    source_stream: str = "stream:ticks:us"
    consumer_group: str = "aggregator"
    bar_stream_prefix: str = "stream:bars"


@dataclass
class DatabaseConfig:
    """Database configuration."""

    host: str = "localhost"
    port: int = 5432
    database: str = "axtrade"
    user: str = "axtrade"
    password: str = "axtrade"
    min_pool_size: int = 2
    max_pool_size: int = 10


@dataclass
class IndicatorConfig:
    """Indicator calculation configuration."""

    sma_period: int = 20
    rsi_period: int = 14


@dataclass
class RiskConfig:
    """Risk management configuration."""

    max_position_size: int = 1000  # Max shares per position
    max_position_value: float = 50000.0  # Max $ per position
    max_order_size: int = 500  # Max shares per order
    max_daily_loss: float = 1000.0  # Max daily loss before halt
    max_open_orders: int = 10  # Max concurrent open orders


@dataclass
class OMSConfig:
    """Order Management System configuration."""

    paper_mode: bool = True
    slippage_bps: int = 10  # basis points
    risk: RiskConfig = field(default_factory=RiskConfig)


@dataclass
class StrategyInstanceConfig:
    """Configuration for a single strategy instance."""

    type: str  # "momentum", "mean_reversion", etc.
    id: str
    enabled: bool = True
    config: dict = field(default_factory=dict)


@dataclass
class StrategiesConfig:
    """Strategies runner configuration."""

    bar_stream: str = "stream:bars:1m:us"
    consumer_group: str = "strategies"
    enabled: list[StrategyInstanceConfig] = field(default_factory=list)


@dataclass
class APIConfig:
    """API server configuration."""

    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = field(default_factory=lambda: ["*"])


@dataclass
class Config:
    """Root configuration."""

    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    aggregator: AggregatorConfig = field(default_factory=AggregatorConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    indicators: IndicatorConfig = field(default_factory=IndicatorConfig)
    oms: OMSConfig = field(default_factory=OMSConfig)
    strategies: StrategiesConfig = field(default_factory=StrategiesConfig)
    api: APIConfig = field(default_factory=APIConfig)


def load_config(path: Optional[Path] = None) -> Config:
    """Load configuration from YAML file.

    Args:
        path: Path to config file. Defaults to config/default.yaml

    Returns:
        Loaded configuration
    """
    if path is None:
        path = Path(__file__).parent.parent.parent.parent / "config" / "default.yaml"

    with open(path) as f:
        data = yaml.safe_load(f)

    gateway_data = data.get("gateway", {})
    redis_data = data.get("redis", {})
    aggregator_data = data.get("aggregator", {})
    database_data = data.get("database", {})
    indicators_data = data.get("indicators", {})
    oms_data = data.get("oms", {})
    strategies_data = data.get("strategies", {})
    api_data = data.get("api", {})

    symbols = [
        SymbolConfig(
            symbol=s["symbol"],
            base_price=s["base_price"],
        )
        for s in gateway_data.get("symbols", [])
    ]

    mock_data = gateway_data.get("mock", {})
    ibkr_data = gateway_data.get("ibkr", {})
    alpaca_data = gateway_data.get("alpaca", {})
    yahoo_data = gateway_data.get("yahoo", {})

    return Config(
        gateway=GatewayConfig(
            adapter=gateway_data.get("adapter", "mock"),
            mock=MockConfig(
                tick_interval_ms=mock_data.get("tick_interval_ms", 500),
                volatility=mock_data.get("volatility", 0.001),
            ),
            ibkr=IBKRConfig(
                host=ibkr_data.get("host", "127.0.0.1"),
                port=ibkr_data.get("port", 7497),
                client_id=ibkr_data.get("client_id", 1),
            ),
            alpaca=AlpacaConfig(
                api_key=alpaca_data.get("api_key", ""),
                secret_key=alpaca_data.get("secret_key", ""),
                feed=alpaca_data.get("feed", "iex"),
                paper=alpaca_data.get("paper", True),
            ),
            yahoo=YahooConfig(
                poll_interval_ms=yahoo_data.get("poll_interval_ms", 5000),
            ),
            symbols=symbols,
        ),
        redis=RedisConfig(
            host=redis_data.get("host", "localhost"),
            port=redis_data.get("port", 6379),
            stream_prefix=redis_data.get("stream_prefix", "stream:ticks"),
        ),
        aggregator=AggregatorConfig(
            intervals=aggregator_data.get("intervals", ["1m", "5m"]),
            source_stream=aggregator_data.get("source_stream", "stream:ticks:us"),
            consumer_group=aggregator_data.get("consumer_group", "aggregator"),
            bar_stream_prefix=aggregator_data.get("bar_stream_prefix", "stream:bars"),
        ),
        database=DatabaseConfig(
            host=database_data.get("host", "localhost"),
            port=database_data.get("port", 5432),
            database=database_data.get("database", "axtrade"),
            user=database_data.get("user", "axtrade"),
            password=database_data.get("password", "axtrade"),
            min_pool_size=database_data.get("min_pool_size", 2),
            max_pool_size=database_data.get("max_pool_size", 10),
        ),
        indicators=IndicatorConfig(
            sma_period=indicators_data.get("sma_period", 20),
            rsi_period=indicators_data.get("rsi_period", 14),
        ),
        oms=OMSConfig(
            paper_mode=oms_data.get("paper_mode", True),
            slippage_bps=oms_data.get("slippage_bps", 10),
            risk=RiskConfig(
                max_position_size=oms_data.get("risk", {}).get("max_position_size", 1000),
                max_position_value=oms_data.get("risk", {}).get("max_position_value", 50000.0),
                max_order_size=oms_data.get("risk", {}).get("max_order_size", 500),
                max_daily_loss=oms_data.get("risk", {}).get("max_daily_loss", 1000.0),
                max_open_orders=oms_data.get("risk", {}).get("max_open_orders", 10),
            ),
        ),
        strategies=StrategiesConfig(
            bar_stream=strategies_data.get("bar_stream", "stream:bars:1m:us"),
            consumer_group=strategies_data.get("consumer_group", "strategies"),
            enabled=[
                StrategyInstanceConfig(
                    type=s["type"],
                    id=s["id"],
                    enabled=s.get("enabled", True),
                    config=s.get("config", {}),
                )
                for s in strategies_data.get("enabled", [])
            ],
        ),
        api=APIConfig(
            host=api_data.get("host", "0.0.0.0"),
            port=api_data.get("port", 8000),
            cors_origins=api_data.get("cors_origins", ["*"]),
        ),
    )
