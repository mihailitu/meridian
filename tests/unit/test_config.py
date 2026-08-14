"""Unit tests for configuration loading and management."""

import tempfile
from pathlib import Path

import pytest
import yaml

from axtrade.common.config import (
    AggregatorConfig,
    APIConfig,
    Config,
    DatabaseConfig,
    GatewayConfig,
    IBKRConfig,
    IndicatorConfig,
    MockConfig,
    OMSConfig,
    RedisConfig,
    RiskConfig,
    StrategiesConfig,
    StrategyInstanceConfig,
    load_config,
)


class TestMockConfig:
    """Tests for MockConfig."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = MockConfig()
        assert config.tick_interval_ms == 500
        assert config.volatility == 0.001

    def test_custom_values(self) -> None:
        """Test custom values."""
        config = MockConfig(tick_interval_ms=100, volatility=0.005)
        assert config.tick_interval_ms == 100
        assert config.volatility == 0.005


class TestIBKRConfig:
    """Tests for IBKRConfig."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = IBKRConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 7497
        assert config.client_id == 1
        assert config.market_data_type == "delayed"
        assert config.max_subscriptions == 90
        assert config.resubscribe_silent_after_seconds == 300

    def test_custom_values(self) -> None:
        """Test custom values."""
        config = IBKRConfig(
            host="192.168.1.100",
            port=4001,
            client_id=5,
            market_data_type="live",
            max_subscriptions=50,
            resubscribe_silent_after_seconds=120,
        )
        assert config.host == "192.168.1.100"
        assert config.port == 4001
        assert config.client_id == 5
        assert config.market_data_type == "live"
        assert config.max_subscriptions == 50
        assert config.resubscribe_silent_after_seconds == 120

    def test_invalid_market_data_type_raises(self) -> None:
        """Test D2: invalid market_data_type is rejected at construction."""
        with pytest.raises(ValueError, match="market_data_type"):
            IBKRConfig(market_data_type="realtime")


class TestGatewayConfig:
    """Tests for GatewayConfig."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = GatewayConfig()
        assert config.adapter == "mock"
        assert isinstance(config.mock, MockConfig)
        assert isinstance(config.ibkr, IBKRConfig)
        assert config.symbols == []
        assert config.tick_staleness_seconds == 300

    def test_with_symbols(self) -> None:
        """Test with symbol configs."""
        from axtrade.common.types import SymbolConfig

        symbols = [SymbolConfig(symbol="AAPL", base_price=185.0)]
        config = GatewayConfig(symbols=symbols)
        assert len(config.symbols) == 1
        assert config.symbols[0].symbol == "AAPL"


class TestRedisConfig:
    """Tests for RedisConfig."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = RedisConfig()
        assert config.host == "localhost"
        assert config.port == 6379
        assert config.stream_prefix == "stream:ticks"
        assert config.stream_maxlen == 100_000
        assert config.consumer_group_start == "$"


class TestAggregatorConfig:
    """Tests for AggregatorConfig."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = AggregatorConfig()
        assert config.intervals == ["1m", "5m"]
        assert config.source_stream == "stream:ticks:us"
        assert config.consumer_group == "aggregator"
        assert config.bar_stream_prefix == "stream:bars"


class TestDatabaseConfig:
    """Tests for DatabaseConfig."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = DatabaseConfig()
        assert config.host == "localhost"
        assert config.port == 5432
        assert config.database == "axtrade"
        assert config.user == "axtrade"
        assert config.password == "axtrade"
        assert config.min_pool_size == 2
        assert config.max_pool_size == 10


class TestIndicatorConfig:
    """Tests for IndicatorConfig."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = IndicatorConfig()
        assert config.sma_period == 20
        assert config.rsi_period == 14
        assert config.bb_period == 20
        assert config.bb_std == 2.0
        assert config.atr_period == 14


class TestRiskConfig:
    """Tests for RiskConfig."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = RiskConfig()
        assert config.max_position_size == 1000
        assert config.max_position_value == 50000.0
        assert config.max_order_size == 500
        assert config.max_daily_loss == 1000.0
        assert config.max_open_orders == 10


class TestOMSConfig:
    """Tests for OMSConfig."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = OMSConfig()
        assert config.paper_mode is True
        assert config.slippage_bps == 10
        assert config.ibkr_client_id == 2
        assert config.ibkr_allow_live is False
        assert isinstance(config.risk, RiskConfig)


class TestStrategyInstanceConfig:
    """Tests for StrategyInstanceConfig."""

    def test_required_fields(self) -> None:
        """Test required fields."""
        config = StrategyInstanceConfig(type="momentum", id="momentum_01")
        assert config.type == "momentum"
        assert config.id == "momentum_01"
        assert config.enabled is True
        assert config.config == {}

    def test_with_config(self) -> None:
        """Test with strategy config."""
        config = StrategyInstanceConfig(
            type="momentum",
            id="momentum_01",
            enabled=False,
            config={"rsi_oversold": 35, "position_size": 200},
        )
        assert config.enabled is False
        assert config.config["rsi_oversold"] == 35


class TestStrategiesConfig:
    """Tests for StrategiesConfig."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = StrategiesConfig()
        assert config.bar_stream == "stream:bars:1m:us"
        assert config.consumer_group == "strategies"
        assert config.control_channel == "axtrade:strategy:control"
        assert config.enabled == []


class TestAPIConfig:
    """Tests for APIConfig."""

    def test_defaults(self) -> None:
        """Test default values."""
        config = APIConfig()
        assert config.host == "127.0.0.1"
        assert config.port == 8000
        assert config.cors_origins == ["*"]
        assert config.api_key == ""


class TestConfig:
    """Tests for root Config."""

    def test_defaults(self) -> None:
        """Test default values create valid config."""
        config = Config()
        assert isinstance(config.gateway, GatewayConfig)
        assert isinstance(config.redis, RedisConfig)
        assert isinstance(config.aggregator, AggregatorConfig)
        assert isinstance(config.database, DatabaseConfig)
        assert isinstance(config.indicators, IndicatorConfig)
        assert isinstance(config.oms, OMSConfig)
        assert isinstance(config.strategies, StrategiesConfig)
        assert isinstance(config.api, APIConfig)


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_from_yaml(self) -> None:
        """Test loading config from YAML file."""
        yaml_content = """
gateway:
  adapter: mock
  mock:
    tick_interval_ms: 250
    volatility: 0.002
  symbols:
    - symbol: AAPL
      base_price: 185.0
    - symbol: MSFT
      base_price: 420.0

redis:
  host: redis.example.com
  port: 6380
  stream_prefix: stream:test
  stream_maxlen: 50000
  consumer_group_start: "0"

aggregator:
  intervals:
    - 1m
    - 5m
    - 15m
  source_stream: stream:test:us
  consumer_group: test-agg

database:
  host: db.example.com
  port: 5433
  database: axtrade_test
  user: testuser
  password: testpass
  min_pool_size: 1
  max_pool_size: 5

indicators:
  sma_period: 25
  rsi_period: 12

oms:
  paper_mode: false
  slippage_bps: 5
  risk:
    max_position_size: 500
    max_position_value: 25000.0
    max_order_size: 250
    max_daily_loss: 500.0
    max_open_orders: 5

strategies:
  bar_stream: stream:bars:5m:us
  consumer_group: test-strategies
  control_channel: test:strategy:control
  enabled:
    - type: momentum
      id: test_momentum
      enabled: true
      config:
        rsi_oversold: 35
        position_size: 50

api:
  host: 127.0.0.1
  port: 9000
  cors_origins:
    - http://localhost:3000
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = Path(f.name)

        try:
            config = load_config(temp_path)

            # Gateway
            assert config.gateway.adapter == "mock"
            assert config.gateway.mock.tick_interval_ms == 250
            assert config.gateway.mock.volatility == 0.002
            assert len(config.gateway.symbols) == 2
            assert config.gateway.symbols[0].symbol == "AAPL"

            # Redis
            assert config.redis.host == "redis.example.com"
            assert config.redis.port == 6380
            assert config.redis.stream_prefix == "stream:test"
            assert config.redis.stream_maxlen == 50_000
            assert config.redis.consumer_group_start == "0"

            # Aggregator
            assert config.aggregator.intervals == ["1m", "5m", "15m"]
            assert config.aggregator.source_stream == "stream:test:us"
            assert config.aggregator.consumer_group == "test-agg"

            # Database
            assert config.database.host == "db.example.com"
            assert config.database.port == 5433
            assert config.database.database == "axtrade_test"
            assert config.database.user == "testuser"
            assert config.database.password == "testpass"
            assert config.database.min_pool_size == 1
            assert config.database.max_pool_size == 5

            # Indicators
            assert config.indicators.sma_period == 25
            assert config.indicators.rsi_period == 12

            # OMS
            assert config.oms.paper_mode is False
            assert config.oms.slippage_bps == 5
            assert config.oms.risk.max_position_size == 500
            assert config.oms.risk.max_position_value == 25000.0
            assert config.oms.risk.max_order_size == 250
            assert config.oms.risk.max_daily_loss == 500.0
            assert config.oms.risk.max_open_orders == 5

            # Strategies
            assert config.strategies.bar_stream == "stream:bars:5m:us"
            assert config.strategies.consumer_group == "test-strategies"
            assert len(config.strategies.enabled) == 1
            assert config.strategies.enabled[0].type == "momentum"
            assert config.strategies.enabled[0].id == "test_momentum"
            assert config.strategies.enabled[0].config["rsi_oversold"] == 35

            # API
            assert config.api.host == "127.0.0.1"
            assert config.api.port == 9000
            assert config.api.cors_origins == ["http://localhost:3000"]
        finally:
            temp_path.unlink()

    def test_load_minimal_yaml(self) -> None:
        """Test loading minimal YAML with defaults."""
        yaml_content = """
gateway:
  adapter: mock
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = Path(f.name)

        try:
            config = load_config(temp_path)

            # Check defaults are applied
            assert config.gateway.adapter == "mock"
            assert config.gateway.mock.tick_interval_ms == 500
            assert config.redis.host == "localhost"
            assert config.redis.stream_maxlen == 100_000
            assert config.redis.consumer_group_start == "$"
            assert config.database.database == "axtrade"
            assert config.indicators.sma_period == 20
            assert config.oms.paper_mode is True
            assert len(config.strategies.enabled) == 0
        finally:
            temp_path.unlink()

    def test_load_empty_yaml_raises(self) -> None:
        """Test loading empty YAML raises AttributeError."""
        yaml_content = ""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = Path(f.name)

        try:
            # Empty YAML returns None, which causes AttributeError
            with pytest.raises(AttributeError):
                load_config(temp_path)
        finally:
            temp_path.unlink()

    def test_load_empty_dict_yaml(self) -> None:
        """Test loading YAML with empty dict uses all defaults."""
        yaml_content = "{}"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = Path(f.name)

        try:
            config = load_config(temp_path)
            # All defaults should be applied
            assert config.gateway.adapter == "mock"
            assert config.redis.host == "localhost"
        finally:
            temp_path.unlink()

    def test_load_nonexistent_file_raises(self) -> None:
        """Test loading nonexistent file raises error."""
        with pytest.raises(FileNotFoundError):
            load_config(Path("/nonexistent/config.yaml"))

    def test_load_ibkr_config(self) -> None:
        """Test loading IBKR adapter config."""
        yaml_content = """
gateway:
  adapter: ibkr
  ibkr:
    host: 192.168.1.50
    port: 4001
    client_id: 10
    market_data_type: live
    max_subscriptions: 45
    resubscribe_silent_after_seconds: 120
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = Path(f.name)

        try:
            config = load_config(temp_path)
            assert config.gateway.adapter == "ibkr"
            assert config.gateway.ibkr.host == "192.168.1.50"
            assert config.gateway.ibkr.port == 4001
            assert config.gateway.ibkr.client_id == 10
            assert config.gateway.ibkr.market_data_type == "live"
            assert config.gateway.ibkr.max_subscriptions == 45
            assert config.gateway.ibkr.resubscribe_silent_after_seconds == 120
        finally:
            temp_path.unlink()

    def test_load_ibkr_max_subscriptions_default(self) -> None:
        """Test D5: gateway.ibkr.max_subscriptions defaults to 90."""
        yaml_content = """
gateway:
  adapter: ibkr
  ibkr:
    host: 192.168.1.50
    port: 4001
    client_id: 10
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = Path(f.name)

        try:
            config = load_config(temp_path)
            assert config.gateway.ibkr.max_subscriptions == 90
        finally:
            temp_path.unlink()

    def test_load_ibkr_resubscribe_silent_after_seconds_default(self) -> None:
        """Test D6: gateway.ibkr.resubscribe_silent_after_seconds defaults to 300."""
        yaml_content = """
gateway:
  adapter: ibkr
  ibkr:
    host: 192.168.1.50
    port: 4001
    client_id: 10
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = Path(f.name)

        try:
            config = load_config(temp_path)
            assert config.gateway.ibkr.resubscribe_silent_after_seconds == 300
        finally:
            temp_path.unlink()

    def test_load_ibkr_market_data_type_default(self) -> None:
        """Test D2: gateway.ibkr.market_data_type defaults to delayed."""
        yaml_content = """
gateway:
  adapter: ibkr
  ibkr:
    host: 192.168.1.50
    port: 4001
    client_id: 10
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = Path(f.name)

        try:
            config = load_config(temp_path)
            assert config.gateway.ibkr.market_data_type == "delayed"
        finally:
            temp_path.unlink()

    def test_load_oms_ibkr_settings(self) -> None:
        """Test D1/D3: oms.ibkr_client_id / oms.ibkr_allow_live round-trip."""
        yaml_content = """
gateway:
  adapter: ibkr

oms:
  paper_mode: false
  ibkr_client_id: 7
  ibkr_allow_live: true
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = Path(f.name)

        try:
            config = load_config(temp_path)
            assert config.oms.ibkr_client_id == 7
            assert config.oms.ibkr_allow_live is True
        finally:
            temp_path.unlink()

    def test_load_oms_ibkr_settings_defaults(self) -> None:
        """Test D1/D3: oms.ibkr_client_id / oms.ibkr_allow_live default when omitted."""
        yaml_content = """
gateway:
  adapter: mock
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = Path(f.name)

        try:
            config = load_config(temp_path)
            assert config.oms.ibkr_client_id == 2
            assert config.oms.ibkr_allow_live is False
        finally:
            temp_path.unlink()

    def test_load_alpaca_config(self) -> None:
        """Test loading Alpaca adapter config."""
        yaml_content = """
gateway:
  adapter: alpaca
  alpaca:
    api_key: test_key
    secret_key: test_secret
    feed: sip
    paper: false
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = Path(f.name)

        try:
            config = load_config(temp_path)
            assert config.gateway.adapter == "alpaca"
            assert config.gateway.alpaca.api_key == "test_key"
            assert config.gateway.alpaca.secret_key == "test_secret"
            assert config.gateway.alpaca.feed == "sip"
            assert config.gateway.alpaca.paper is False
        finally:
            temp_path.unlink()

    def test_load_tick_staleness_seconds(self) -> None:
        """Test loading the gateway tick-staleness watchdog threshold."""
        yaml_content = """
gateway:
  adapter: mock
  tick_staleness_seconds: 42
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = Path(f.name)

        try:
            config = load_config(temp_path)
            assert config.gateway.tick_staleness_seconds == 42
        finally:
            temp_path.unlink()

    def test_load_yahoo_config(self) -> None:
        """Test loading Yahoo adapter config."""
        yaml_content = """
gateway:
  adapter: yahoo
  yahoo:
    poll_interval_ms: 10000
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            f.write(yaml_content)
            f.flush()
            temp_path = Path(f.name)

        try:
            config = load_config(temp_path)
            assert config.gateway.adapter == "yahoo"
            assert config.gateway.yahoo.poll_interval_ms == 10000
        finally:
            temp_path.unlink()


class TestLocalOverlay:
    """local.yaml next to the loaded config is deep-merged on top of it
    (per-machine overrides, e.g. IB Gateway port 4002 vs TWS 7497)."""

    BASE = """
gateway:
  adapter: mock
  ibkr:
    host: "127.0.0.1"
    port: 7497
    client_id: 1

aggregator:
  intervals: ["1m", "5m"]
"""

    def _write(self, tmp_path: Path, base: str, local: str | None) -> Path:
        config_path = tmp_path / "default.yaml"
        config_path.write_text(base)
        if local is not None:
            (tmp_path / "local.yaml").write_text(local)
        return config_path

    def test_no_local_yaml_leaves_config_unchanged(self, tmp_path: Path) -> None:
        config = load_config(self._write(tmp_path, self.BASE, None))
        assert config.gateway.ibkr.port == 7497

    def test_nested_override_merges_keeping_siblings(self, tmp_path: Path) -> None:
        local = """
gateway:
  ibkr:
    port: 4002
"""
        config = load_config(self._write(tmp_path, self.BASE, local))
        assert config.gateway.ibkr.port == 4002
        # Siblings at every level of the merged branch survive.
        assert config.gateway.ibkr.host == "127.0.0.1"
        assert config.gateway.ibkr.client_id == 1
        assert config.gateway.adapter == "mock"

    def test_lists_are_replaced_not_merged(self, tmp_path: Path) -> None:
        local = """
aggregator:
  intervals: ["1m"]
"""
        config = load_config(self._write(tmp_path, self.BASE, local))
        assert config.aggregator.intervals == ["1m"]

    def test_empty_local_yaml_is_harmless(self, tmp_path: Path) -> None:
        config = load_config(self._write(tmp_path, self.BASE, ""))
        assert config.gateway.ibkr.port == 7497
