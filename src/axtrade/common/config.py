"""Configuration loading and management."""

import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Optional

import yaml

from .types import SymbolConfig


@dataclass
class MockConfig:
    """Mock adapter configuration."""

    tick_interval_ms: int = 500
    volatility: float = 0.001
    # Seeds the adapter's own random.Random instance for deterministic tick
    # sequences (e.g. reproducible tests). None = nondeterministic, matching
    # the previous global-random behavior.
    seed: Optional[int] = None


@dataclass
class IBKRConfig:
    """IBKR adapter configuration."""

    host: str = "127.0.0.1"
    port: int = 7497
    client_id: int = 1
    # "live" | "delayed" -> reqMarketDataType(1) / reqMarketDataType(3).
    # Default delayed: a fresh paper account has no paid market-data
    # subscriptions, and live streaming data errors (code 354) without one.
    market_data_type: str = "delayed"
    # Cap on total concurrent market-data subscriptions (initial config
    # symbols + dynamic add_symbols, e.g. discovery auto_subscribe). IBKR's
    # default market-data line limit is ~100; add_symbols logs and skips
    # past this rather than raising (D5).
    max_subscriptions: int = 90
    # Resubscribe symbols that produced no ticks for this long, in seconds;
    # 0 = off (D6, S1 finding 1: delayed-feed subscriptions opened pre-open
    # silently never start streaming).
    resubscribe_silent_after_seconds: int = 300

    def __post_init__(self) -> None:
        if self.market_data_type not in ("live", "delayed"):
            raise ValueError(
                f"ibkr.market_data_type must be 'live' or 'delayed', "
                f"got {self.market_data_type!r}"
            )


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
    control_channel: str = "axtrade:gateway:control"
    # Seconds since the last received tick before the staleness watchdog logs
    # a warning (covers all adapters, not just Alpaca). 0 disables.
    tick_staleness_seconds: int = 300


@dataclass
class RedisConfig:
    """Redis configuration."""

    host: str = "localhost"
    port: int = 6379
    db: int = 0
    stream_prefix: str = "stream:ticks"
    # Approximate cap per stream (XADD MAXLEN ~), 0 = unlimited.
    stream_maxlen: int = 100_000
    # Consumer group creation start id. "$" = new messages only (default,
    # avoids replaying a long-lived stream's full retained history on group
    # re-creation). Fulltest pins "0" so replay never misses early ticks.
    consumer_group_start: str = "$"


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
class RegimeConfig:
    """Regime detection configuration."""

    sma_short_period: int = 10
    sma_long_period: int = 20
    volatility_lookback: int = 20
    atr_period: int = 14


@dataclass
class IndicatorConfig:
    """Indicator calculation configuration."""

    sma_period: int = 20
    rsi_period: int = 14
    bb_period: int = 20
    bb_std: float = 2.0
    atr_period: int = 14
    regime: RegimeConfig = field(default_factory=RegimeConfig)


@dataclass
class RiskConfig:
    """Risk management configuration."""

    max_position_size: int = 1000  # Max shares per position
    max_position_value: float = 50000.0  # Max $ per position
    max_order_size: int = 500  # Max shares per order
    max_daily_loss: float = 1000.0  # Max daily loss before halt
    max_open_orders: int = 10  # Max concurrent open orders


@dataclass
class CommissionConfig:
    """Commission model configuration (IBKR Pro Fixed rates)."""

    per_share: Decimal = Decimal("0.005")
    minimum: Decimal = Decimal("1.00")
    max_pct: Decimal = Decimal("1.0")  # 1% of trade value


@dataclass
class OMSConfig:
    """Order Management System configuration."""

    paper_mode: bool = True
    slippage_bps: int = 10  # basis points
    max_positions: int = 20
    # When set, the PaperBroker tracks cash and rejects buys that would
    # overdraw. None = unlimited cash (legacy behavior, used by live mode
    # where the real broker enforces cash). Fulltest sets this from
    # --capital so the simulation can't accumulate unbounded phantom buys.
    initial_capital: Optional[Decimal] = None
    # When > 0, the PaperBroker rejects orders larger than this fraction of
    # the symbol's last known bar volume (0 = disabled). Audit C3.
    max_volume_participation: float = 0.0
    # Order connection's IBKR clientId. Must differ from gateway.ibkr.client_id
    # (1): gateway and strategy-runner are separate processes, both holding
    # live IB API connections, and IBKR rejects a second connection reusing
    # the same clientId. See docs/ibkr-connection-design.md D1.
    ibkr_client_id: int = 2
    # Refuses IBKRBroker.connect() on live ports (TWS 7496 / IB Gateway 4001)
    # unless explicitly set. Live (real-money) trading is out of scope until
    # a strategy earns it. See docs/ibkr-connection-design.md D3.
    ibkr_allow_live: bool = False
    risk: RiskConfig = field(default_factory=RiskConfig)
    commission: CommissionConfig = field(default_factory=CommissionConfig)


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
    control_channel: str = "axtrade:strategy:control"
    enabled: list[StrategyInstanceConfig] = field(default_factory=list)


@dataclass
class APIConfig:
    """API server configuration."""

    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] = field(default_factory=lambda: ["*"])
    # Empty disables auth on mutating endpoints. AXTRADE_API_KEY env var
    # (see .env, same mechanism as Alpaca creds) takes precedence over this.
    api_key: str = ""


@dataclass
class ScreenerInstanceConfig:
    """Configuration for a single screener instance."""

    type: str  # "momentum", "volatility", "volume", "trend"
    name: str
    enabled: bool = True
    params: dict = field(default_factory=dict)


@dataclass
class DiscoveryConfig:
    """Discovery service configuration."""

    enabled: bool = True
    scan_interval_seconds: int = 300  # 5 minutes
    bar_limit: int = 50
    interval: str = "1m"
    auto_subscribe: bool = False
    min_score: float = 60.0
    max_positions: int = 10
    control_channel: str = "axtrade:discovery:control"
    screeners: list[ScreenerInstanceConfig] = field(default_factory=list)


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
    discovery: DiscoveryConfig = field(default_factory=DiscoveryConfig)


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base recursively: nested dicts merge key-by-key,
    everything else (scalars, lists) is replaced by the override value."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Optional[Path] = None) -> Config:
    """Load configuration from YAML file.

    If a `local.yaml` exists next to the loaded file, it is deep-merged on
    top — the gitignored per-machine overlay (e.g. gateway.ibkr.port 4002
    on a workstation running IB Gateway instead of TWS). Keep it to
    machine-local facts; anything meant for every machine belongs in
    default.yaml.

    Args:
        path: Path to config file. Defaults to config/default.yaml

    Returns:
        Loaded configuration
    """
    if path is None:
        path = Path(__file__).parent.parent.parent.parent / "config" / "default.yaml"

    with open(path) as f:
        data = yaml.safe_load(f)

    local_path = path.parent / "local.yaml"
    if local_path.exists():
        with open(local_path) as f:
            local_data = yaml.safe_load(f) or {}
        data = _deep_merge(data or {}, local_data)

    gateway_data = data.get("gateway", {})
    redis_data = data.get("redis", {})
    aggregator_data = data.get("aggregator", {})
    database_data = data.get("database", {})
    indicators_data = data.get("indicators", {})
    oms_data = data.get("oms", {})
    strategies_data = data.get("strategies", {})
    api_data = data.get("api", {})
    discovery_data = data.get("discovery", {})

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
                seed=mock_data.get("seed"),
            ),
            ibkr=IBKRConfig(
                host=ibkr_data.get("host", "127.0.0.1"),
                port=ibkr_data.get("port", 7497),
                client_id=ibkr_data.get("client_id", 1),
                market_data_type=ibkr_data.get("market_data_type", "delayed"),
                max_subscriptions=ibkr_data.get("max_subscriptions", 90),
                resubscribe_silent_after_seconds=ibkr_data.get(
                    "resubscribe_silent_after_seconds", 300
                ),
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
            control_channel=gateway_data.get("control_channel", "axtrade:gateway:control"),
            tick_staleness_seconds=gateway_data.get("tick_staleness_seconds", 300),
        ),
        redis=RedisConfig(
            host=redis_data.get("host", "localhost"),
            port=redis_data.get("port", 6379),
            db=redis_data.get("db", 0),
            stream_prefix=redis_data.get("stream_prefix", "stream:ticks"),
            stream_maxlen=redis_data.get("stream_maxlen", 100_000),
            consumer_group_start=redis_data.get("consumer_group_start", "$"),
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
            bb_period=indicators_data.get("bb_period", 20),
            bb_std=indicators_data.get("bb_std", 2.0),
            atr_period=indicators_data.get("atr_period", 14),
            regime=RegimeConfig(
                sma_short_period=indicators_data.get("regime", {}).get("sma_short_period", 10),
                sma_long_period=indicators_data.get("regime", {}).get("sma_long_period", 20),
                volatility_lookback=indicators_data.get("regime", {}).get("volatility_lookback", 20),
                atr_period=indicators_data.get("regime", {}).get("atr_period", 14),
            ),
        ),
        oms=OMSConfig(
            paper_mode=oms_data.get("paper_mode", True),
            slippage_bps=oms_data.get("slippage_bps", 10),
            max_positions=oms_data.get("max_positions", 20),
            max_volume_participation=oms_data.get("max_volume_participation", 0.0),
            ibkr_client_id=oms_data.get("ibkr_client_id", 2),
            ibkr_allow_live=oms_data.get("ibkr_allow_live", False),
            risk=RiskConfig(
                max_position_size=oms_data.get("risk", {}).get("max_position_size", 1000),
                max_position_value=oms_data.get("risk", {}).get("max_position_value", 50000.0),
                max_order_size=oms_data.get("risk", {}).get("max_order_size", 500),
                max_daily_loss=oms_data.get("risk", {}).get("max_daily_loss", 1000.0),
                max_open_orders=oms_data.get("risk", {}).get("max_open_orders", 10),
            ),
            commission=CommissionConfig(
                per_share=Decimal(str(oms_data.get("commission", {}).get("per_share", "0.005"))),
                minimum=Decimal(str(oms_data.get("commission", {}).get("minimum", "1.00"))),
                max_pct=Decimal(str(oms_data.get("commission", {}).get("max_pct", "1.0"))),
            ),
        ),
        strategies=StrategiesConfig(
            bar_stream=strategies_data.get("bar_stream", "stream:bars:1m:us"),
            consumer_group=strategies_data.get("consumer_group", "strategies"),
            control_channel=strategies_data.get("control_channel", "axtrade:strategy:control"),
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
            host=api_data.get("host", "127.0.0.1"),
            port=api_data.get("port", 8000),
            cors_origins=api_data.get("cors_origins", ["*"]),
            # AXTRADE_API_KEY env var (loaded via python-dotenv, same as
            # ALPACA_API_KEY) takes precedence over the yaml value.
            api_key=os.environ.get("AXTRADE_API_KEY", api_data.get("api_key", "")),
        ),
        discovery=DiscoveryConfig(
            enabled=discovery_data.get("enabled", True),
            scan_interval_seconds=discovery_data.get("scan_interval_seconds", 300),
            bar_limit=discovery_data.get("bar_limit", 50),
            interval=discovery_data.get("interval", "1m"),
            auto_subscribe=discovery_data.get("auto_subscribe", False),
            min_score=discovery_data.get("min_score", 60.0),
            max_positions=discovery_data.get("max_positions", 10),
            control_channel=discovery_data.get("control_channel", "axtrade:discovery:control"),
            screeners=[
                ScreenerInstanceConfig(
                    type=s["type"],
                    name=s["name"],
                    enabled=s.get("enabled", True),
                    params=s.get("params", {}),
                )
                for s in discovery_data.get("screeners", [])
            ],
        ),
    )
