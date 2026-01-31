"""Unit tests for Redis messaging helpers."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from axtrade.common import (
    AggregatorConfig,
    Bar,
    RedisConfig,
    StrategiesConfig,
    Tick,
)
from axtrade.common.messaging import (
    BarConsumer,
    BarPublisher,
    RedisConsumer,
    RedisPublisher,
)


class TestRedisPublisher:
    """Tests for RedisPublisher."""

    @pytest.fixture
    def config(self) -> RedisConfig:
        """Create Redis config for testing."""
        return RedisConfig(host="localhost", port=6379, stream_prefix="stream:ticks")

    @pytest.fixture
    def publisher(self, config: RedisConfig) -> RedisPublisher:
        """Create RedisPublisher instance."""
        return RedisPublisher(config)

    async def test_connect(self, publisher: RedisPublisher) -> None:
        """Test Redis connection."""
        mock_redis = AsyncMock()

        with patch(
            "axtrade.common.messaging.redis.Redis", return_value=mock_redis
        ):
            await publisher.connect()

        mock_redis.ping.assert_called_once()
        assert publisher.connected is True

    async def test_disconnect(self, publisher: RedisPublisher) -> None:
        """Test Redis disconnection."""
        mock_redis = AsyncMock()
        publisher._client = mock_redis

        await publisher.disconnect()

        mock_redis.aclose.assert_called_once()
        assert publisher._client is None
        assert publisher.connected is False

    async def test_publish_tick(self, publisher: RedisPublisher) -> None:
        """Test tick publishing."""
        mock_redis = AsyncMock()
        mock_redis.xadd.return_value = "1234567890-0"
        publisher._client = mock_redis

        tick = Tick(
            symbol="AAPL",
            price=185.50,
            timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
            bid=185.45,
            ask=185.55,
            volume=1000,
        )

        message_id = await publisher.publish_tick(tick, market="us")

        assert message_id == "1234567890-0"
        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "stream:ticks:us"

    async def test_publish_tick_not_connected_raises(
        self, publisher: RedisPublisher
    ) -> None:
        """Test publish raises when not connected."""
        tick = Tick(symbol="AAPL", price=185.50, timestamp=datetime.now(timezone.utc))

        with pytest.raises(RuntimeError, match="Not connected"):
            await publisher.publish_tick(tick)

    def test_connected_property(self, publisher: RedisPublisher) -> None:
        """Test connected property."""
        assert publisher.connected is False
        publisher._client = MagicMock()
        assert publisher.connected is True


class TestRedisConsumer:
    """Tests for RedisConsumer."""

    @pytest.fixture
    def redis_config(self) -> RedisConfig:
        """Create Redis config for testing."""
        return RedisConfig(host="localhost", port=6379)

    @pytest.fixture
    def aggregator_config(self) -> AggregatorConfig:
        """Create aggregator config for testing."""
        return AggregatorConfig(
            source_stream="stream:ticks:us",
            consumer_group="test-aggregator",
        )

    @pytest.fixture
    def consumer(
        self, redis_config: RedisConfig, aggregator_config: AggregatorConfig
    ) -> RedisConsumer:
        """Create RedisConsumer instance."""
        return RedisConsumer(redis_config, aggregator_config)

    async def test_connect_creates_group(
        self, consumer: RedisConsumer, aggregator_config: AggregatorConfig
    ) -> None:
        """Test connect creates consumer group."""
        mock_redis = AsyncMock()

        with patch(
            "axtrade.common.messaging.redis.Redis", return_value=mock_redis
        ):
            await consumer.connect()

        mock_redis.ping.assert_called_once()
        mock_redis.xgroup_create.assert_called_once_with(
            aggregator_config.source_stream,
            aggregator_config.consumer_group,
            id="0",
            mkstream=True,
        )

    async def test_connect_handles_existing_group(
        self, consumer: RedisConsumer
    ) -> None:
        """Test connect ignores BUSYGROUP error."""
        import redis

        mock_redis = AsyncMock()
        mock_redis.xgroup_create.side_effect = redis.ResponseError("BUSYGROUP")

        with patch(
            "axtrade.common.messaging.redis.Redis", return_value=mock_redis
        ):
            # Should not raise
            await consumer.connect()

    async def test_connect_raises_other_errors(
        self, consumer: RedisConsumer
    ) -> None:
        """Test connect raises non-BUSYGROUP errors."""
        import redis

        mock_redis = AsyncMock()
        mock_redis.xgroup_create.side_effect = redis.ResponseError("OTHER ERROR")

        with patch(
            "axtrade.common.messaging.redis.Redis", return_value=mock_redis
        ):
            with pytest.raises(redis.ResponseError, match="OTHER ERROR"):
                await consumer.connect()

    async def test_disconnect(self, consumer: RedisConsumer) -> None:
        """Test Redis disconnection."""
        mock_redis = AsyncMock()
        consumer._client = mock_redis

        await consumer.disconnect()

        mock_redis.aclose.assert_called_once()
        assert consumer._client is None

    async def test_consume_yields_ticks(
        self, consumer: RedisConsumer, aggregator_config: AggregatorConfig
    ) -> None:
        """Test consuming ticks from stream."""
        mock_redis = AsyncMock()

        # Simulate messages from Redis
        messages = [
            (
                aggregator_config.source_stream,
                [
                    (
                        "1234567890-0",
                        {
                            "symbol": "AAPL",
                            "price": "185.50",
                            "timestamp": "2024-01-15T09:30:00+00:00",
                            "bid": "185.45",
                            "ask": "185.55",
                            "volume": "1000",
                        },
                    )
                ],
            )
        ]

        call_count = 0

        async def mock_xreadgroup(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return messages
            consumer._client = None  # Stop consuming
            return []

        mock_redis.xreadgroup = mock_xreadgroup
        mock_redis.xack = AsyncMock()
        consumer._client = mock_redis

        ticks = []
        async for tick in consumer.consume("test-consumer"):
            ticks.append(tick)

        assert len(ticks) == 1
        assert ticks[0].symbol == "AAPL"
        assert ticks[0].price == 185.50
        assert ticks[0].bid == 185.45

    async def test_consume_not_connected_raises(
        self, consumer: RedisConsumer
    ) -> None:
        """Test consume raises when not connected."""
        with pytest.raises(RuntimeError, match="Not connected"):
            async for _ in consumer.consume("test"):
                pass

    async def test_parse_tick_valid(self, consumer: RedisConsumer) -> None:
        """Test parsing valid tick data."""
        data = {
            "symbol": "AAPL",
            "price": "185.50",
            "timestamp": "2024-01-15T09:30:00+00:00",
            "bid": "185.45",
            "ask": "185.55",
            "volume": "1000",
        }

        tick = consumer._parse_tick(data)

        assert tick is not None
        assert tick.symbol == "AAPL"
        assert tick.price == 185.50
        assert tick.bid == 185.45
        assert tick.ask == 185.55
        assert tick.volume == 1000

    async def test_parse_tick_minimal(self, consumer: RedisConsumer) -> None:
        """Test parsing tick with minimal data."""
        data = {
            "symbol": "AAPL",
            "price": "185.50",
        }

        tick = consumer._parse_tick(data)

        assert tick is not None
        assert tick.symbol == "AAPL"
        assert tick.price == 185.50
        assert tick.bid is None
        assert tick.ask is None
        assert tick.volume is None

    async def test_parse_tick_invalid(self, consumer: RedisConsumer) -> None:
        """Test parsing invalid tick data returns None."""
        data = {"invalid": "data"}

        tick = consumer._parse_tick(data)

        assert tick is None

    def test_connected_property(self, consumer: RedisConsumer) -> None:
        """Test connected property."""
        assert consumer.connected is False
        consumer._client = MagicMock()
        assert consumer.connected is True


class TestBarPublisher:
    """Tests for BarPublisher."""

    @pytest.fixture
    def config(self) -> RedisConfig:
        """Create Redis config for testing."""
        return RedisConfig(host="localhost", port=6379)

    @pytest.fixture
    def publisher(self, config: RedisConfig) -> BarPublisher:
        """Create BarPublisher instance."""
        return BarPublisher(config, bar_stream_prefix="stream:bars")

    async def test_connect(self, publisher: BarPublisher) -> None:
        """Test Redis connection."""
        mock_redis = AsyncMock()

        with patch(
            "axtrade.common.messaging.redis.Redis", return_value=mock_redis
        ):
            await publisher.connect()

        mock_redis.ping.assert_called_once()
        assert publisher.connected is True

    async def test_disconnect(self, publisher: BarPublisher) -> None:
        """Test Redis disconnection."""
        mock_redis = AsyncMock()
        publisher._client = mock_redis

        await publisher.disconnect()

        mock_redis.aclose.assert_called_once()
        assert publisher._client is None

    async def test_publish_bar(self, publisher: BarPublisher) -> None:
        """Test bar publishing."""
        mock_redis = AsyncMock()
        mock_redis.xadd.return_value = "1234567890-0"
        publisher._client = mock_redis

        bar = Bar(
            symbol="AAPL",
            open=185.0,
            high=186.0,
            low=184.0,
            close=185.50,
            volume=10000,
            timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
        )

        message_id = await publisher.publish_bar(
            bar, interval="1m", market="us", sma_20=184.5, rsi_14=55.5
        )

        assert message_id == "1234567890-0"
        mock_redis.xadd.assert_called_once()
        call_args = mock_redis.xadd.call_args
        assert call_args[0][0] == "stream:bars:1m:us"
        data = call_args[0][1]
        assert data["sma_20"] == "184.5"
        assert data["rsi_14"] == "55.5"

    async def test_publish_bar_without_indicators(
        self, publisher: BarPublisher
    ) -> None:
        """Test bar publishing without indicators."""
        mock_redis = AsyncMock()
        mock_redis.xadd.return_value = "1234567890-0"
        publisher._client = mock_redis

        bar = Bar(
            symbol="AAPL",
            open=185.0,
            high=186.0,
            low=184.0,
            close=185.50,
            volume=10000,
            timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
        )

        await publisher.publish_bar(bar, interval="1m")

        data = mock_redis.xadd.call_args[0][1]
        assert data["sma_20"] == ""
        assert data["rsi_14"] == ""

    async def test_publish_bar_not_connected_raises(
        self, publisher: BarPublisher
    ) -> None:
        """Test publish raises when not connected."""
        bar = Bar(
            symbol="AAPL",
            open=185.0,
            high=186.0,
            low=184.0,
            close=185.50,
            volume=10000,
            timestamp=datetime.now(timezone.utc),
        )

        with pytest.raises(RuntimeError, match="Not connected"):
            await publisher.publish_bar(bar, interval="1m")


class TestBarConsumer:
    """Tests for BarConsumer."""

    @pytest.fixture
    def redis_config(self) -> RedisConfig:
        """Create Redis config for testing."""
        return RedisConfig(host="localhost", port=6379)

    @pytest.fixture
    def strategies_config(self) -> StrategiesConfig:
        """Create strategies config for testing."""
        return StrategiesConfig(
            bar_stream="stream:bars:1m:us",
            consumer_group="test-strategies",
        )

    @pytest.fixture
    def consumer(
        self, redis_config: RedisConfig, strategies_config: StrategiesConfig
    ) -> BarConsumer:
        """Create BarConsumer instance."""
        return BarConsumer(redis_config, strategies_config)

    async def test_connect_creates_group(
        self, consumer: BarConsumer, strategies_config: StrategiesConfig
    ) -> None:
        """Test connect creates consumer group."""
        mock_redis = AsyncMock()

        with patch(
            "axtrade.common.messaging.redis.Redis", return_value=mock_redis
        ):
            await consumer.connect()

        mock_redis.ping.assert_called_once()
        mock_redis.xgroup_create.assert_called_once_with(
            strategies_config.bar_stream,
            strategies_config.consumer_group,
            id="0",
            mkstream=True,
        )

    async def test_disconnect(self, consumer: BarConsumer) -> None:
        """Test Redis disconnection."""
        mock_redis = AsyncMock()
        consumer._client = mock_redis

        await consumer.disconnect()

        mock_redis.aclose.assert_called_once()
        assert consumer._client is None

    async def test_consume_yields_bars(
        self, consumer: BarConsumer, strategies_config: StrategiesConfig
    ) -> None:
        """Test consuming bars from stream."""
        mock_redis = AsyncMock()

        # Simulate messages from Redis
        messages = [
            (
                strategies_config.bar_stream,
                [
                    (
                        "1234567890-0",
                        {
                            "symbol": "AAPL",
                            "open": "185.0",
                            "high": "186.0",
                            "low": "184.0",
                            "close": "185.50",
                            "volume": "10000",
                            "timestamp": "2024-01-15T09:30:00+00:00",
                            "sma_20": "184.5",
                            "rsi_14": "55.5",
                        },
                    )
                ],
            )
        ]

        call_count = 0

        async def mock_xreadgroup(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return messages
            consumer._client = None
            return []

        mock_redis.xreadgroup = mock_xreadgroup
        mock_redis.xack = AsyncMock()
        consumer._client = mock_redis

        bars = []
        async for bar_data in consumer.consume("test-consumer"):
            bars.append(bar_data)

        assert len(bars) == 1
        assert bars[0]["bar"].symbol == "AAPL"
        assert bars[0]["bar"].close == 185.50
        assert bars[0]["sma_20"] == 184.5
        assert bars[0]["rsi_14"] == 55.5

    async def test_consume_not_connected_raises(
        self, consumer: BarConsumer
    ) -> None:
        """Test consume raises when not connected."""
        with pytest.raises(RuntimeError, match="Not connected"):
            async for _ in consumer.consume("test"):
                pass

    async def test_parse_bar_data_valid(self, consumer: BarConsumer) -> None:
        """Test parsing valid bar data."""
        data = {
            "symbol": "AAPL",
            "open": "185.0",
            "high": "186.0",
            "low": "184.0",
            "close": "185.50",
            "volume": "10000",
            "timestamp": "2024-01-15T09:30:00+00:00",
            "sma_20": "184.5",
            "rsi_14": "55.5",
        }

        result = consumer._parse_bar_data(data)

        assert result is not None
        assert result["bar"].symbol == "AAPL"
        assert result["bar"].close == 185.50
        assert result["sma_20"] == 184.5
        assert result["rsi_14"] == 55.5

    async def test_parse_bar_data_without_indicators(
        self, consumer: BarConsumer
    ) -> None:
        """Test parsing bar data without indicators."""
        data = {
            "symbol": "AAPL",
            "open": "185.0",
            "high": "186.0",
            "low": "184.0",
            "close": "185.50",
            "volume": "10000",
            "timestamp": "2024-01-15T09:30:00+00:00",
            "sma_20": "",
            "rsi_14": "",
        }

        result = consumer._parse_bar_data(data)

        assert result is not None
        assert result["sma_20"] is None
        assert result["rsi_14"] is None

    async def test_parse_bar_data_invalid(self, consumer: BarConsumer) -> None:
        """Test parsing invalid bar data returns None."""
        data = {"invalid": "data"}

        result = consumer._parse_bar_data(data)

        assert result is None

    def test_connected_property(self, consumer: BarConsumer) -> None:
        """Test connected property."""
        assert consumer.connected is False
        consumer._client = MagicMock()
        assert consumer.connected is True
