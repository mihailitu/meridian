"""Unit tests for Redis messaging helpers."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog

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

    async def test_publish_tick_uses_stream_maxlen_by_default(
        self, publisher: RedisPublisher
    ) -> None:
        """xadd is called with maxlen=100000, approximate=True by default
        (audit P1-8a)."""
        mock_redis = AsyncMock()
        mock_redis.xadd.return_value = "1234567890-0"
        publisher._client = mock_redis

        tick = Tick(symbol="AAPL", price=185.50, timestamp=datetime.now(timezone.utc))

        await publisher.publish_tick(tick, market="us")

        call_kwargs = mock_redis.xadd.call_args[1]
        assert call_kwargs["maxlen"] == 100_000
        assert call_kwargs["approximate"] is True

    async def test_publish_tick_omits_maxlen_when_unlimited(self) -> None:
        """stream_maxlen=0 disables trimming: xadd is called without maxlen."""
        config = RedisConfig(host="localhost", port=6379, stream_maxlen=0)
        publisher = RedisPublisher(config)
        mock_redis = AsyncMock()
        mock_redis.xadd.return_value = "1234567890-0"
        publisher._client = mock_redis

        tick = Tick(symbol="AAPL", price=185.50, timestamp=datetime.now(timezone.utc))

        await publisher.publish_tick(tick, market="us")

        call_kwargs = mock_redis.xadd.call_args[1]
        assert "maxlen" not in call_kwargs
        assert "approximate" not in call_kwargs

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
            id="$",
            mkstream=True,
        )

    async def test_connect_creates_group_with_configured_start_id(
        self, aggregator_config: AggregatorConfig
    ) -> None:
        """consumer_group_start="0" (fulltest's replay setting) is passed
        through to xgroup_create (audit P1-8b)."""
        redis_config = RedisConfig(host="localhost", port=6379, consumer_group_start="0")
        consumer = RedisConsumer(redis_config, aggregator_config)
        mock_redis = AsyncMock()

        with patch(
            "axtrade.common.messaging.redis.Redis", return_value=mock_redis
        ):
            await consumer.connect()

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
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", [], []))
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

    async def test_parse_tick_ibkr_float_volume_string(
        self, consumer: RedisConsumer
    ) -> None:
        """ib_insync's Ticker.volume is a float; Tick.to_dict serializes it
        as e.g. "2417.0". This must parse to an int volume, not be dropped
        (regression test for audit P0-4 kill (a))."""
        data = {
            "symbol": "AAPL",
            "price": "185.50",
            "volume": "2417.0",
        }

        tick = consumer._parse_tick(data)

        assert tick is not None
        assert tick.volume == 2417

    async def test_tick_volume_round_trip_through_to_dict(
        self, consumer: RedisConsumer
    ) -> None:
        """A Tick with an int volume survives a to_dict -> _parse_tick round trip."""
        original = Tick(
            symbol="AAPL",
            price=185.50,
            timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
            volume=2417,
        )

        tick = consumer._parse_tick(original.to_dict())

        assert tick is not None
        assert tick.volume == 2417

    async def test_parse_tick_zero_values_round_trip(
        self, consumer: RedisConsumer
    ) -> None:
        """bid=0.0/ask=0.0/volume=0 must round-trip as 0, not None or ""."""
        original = Tick(
            symbol="AAPL",
            price=185.50,
            timestamp=datetime(2024, 1, 15, 9, 30, tzinfo=timezone.utc),
            bid=0.0,
            ask=0.0,
            volume=0,
        )

        data = original.to_dict()
        assert data["bid"] == "0.0"
        assert data["ask"] == "0.0"
        assert data["volume"] == "0"

        tick = consumer._parse_tick(data)

        assert tick is not None
        assert tick.bid == 0.0
        assert tick.ask == 0.0
        assert tick.volume == 0

    async def test_consume_acks_and_logs_poison_tick_message(
        self, consumer: RedisConsumer, aggregator_config: AggregatorConfig
    ) -> None:
        """An unparseable message must be acked (not left in the PEL forever)
        and logged, and stream processing must continue past it."""
        mock_redis = AsyncMock()

        poison_message = (
            aggregator_config.source_stream,
            [("poison-0", {"invalid": "data"})],
        )
        good_message = (
            aggregator_config.source_stream,
            [
                (
                    "good-0",
                    {
                        "symbol": "AAPL",
                        "price": "185.50",
                        "timestamp": "2024-01-15T09:30:00+00:00",
                        "volume": "1000",
                    },
                )
            ],
        )

        call_count = 0

        async def mock_xreadgroup(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [poison_message]
            if call_count == 2:
                return [good_message]
            consumer._client = None
            return []

        mock_redis.xreadgroup = mock_xreadgroup
        mock_redis.xack = AsyncMock()
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", [], []))
        consumer._client = mock_redis

        ticks = []
        with structlog.testing.capture_logs() as cap_logs:
            async for tick in consumer.consume("test-consumer"):
                ticks.append(tick)

        assert len(ticks) == 1
        assert ticks[0].symbol == "AAPL"

        events = [entry["event"] for entry in cap_logs]
        assert "unparseable_tick_message" in events

        mock_redis.xack.assert_any_call(
            aggregator_config.source_stream, aggregator_config.consumer_group, "poison-0"
        )
        mock_redis.xack.assert_any_call(
            aggregator_config.source_stream, aggregator_config.consumer_group, "good-0"
        )

    def test_connected_property(self, consumer: RedisConsumer) -> None:
        """Test connected property."""
        assert consumer.connected is False
        consumer._client = MagicMock()
        assert consumer.connected is True


class TestRedisConsumerPelRecovery:
    """Tests for the startup PEL-recovery pass in RedisConsumer.consume()
    (audit P2-7)."""

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

    async def test_consume_replays_own_pending_before_fresh_messages(
        self, consumer: RedisConsumer, aggregator_config: AggregatorConfig
    ) -> None:
        """Messages already in this consumer's own PEL (delivered before a
        crash) are replayed before fresh (">") messages, and both are
        acked."""
        mock_redis = AsyncMock()

        pending_message = (
            aggregator_config.source_stream,
            [
                (
                    "100-0",
                    {
                        "symbol": "PEND",
                        "price": "10.0",
                        "timestamp": "2024-01-15T09:30:00+00:00",
                    },
                )
            ],
        )
        fresh_message = (
            aggregator_config.source_stream,
            [
                (
                    "200-0",
                    {
                        "symbol": "FRESH",
                        "price": "20.0",
                        "timestamp": "2024-01-15T09:31:00+00:00",
                    },
                )
            ],
        )

        calls = []

        async def mock_xreadgroup(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return [pending_message]
            if len(calls) == 2:
                return []  # own PEL drained
            if len(calls) == 3:
                return [fresh_message]
            consumer._client = None
            return []

        mock_redis.xreadgroup = mock_xreadgroup
        mock_redis.xack = AsyncMock()
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", [], []))
        consumer._client = mock_redis

        ticks = []
        async for tick in consumer.consume("stable-consumer"):
            ticks.append(tick)

        assert [t.symbol for t in ticks] == ["PEND", "FRESH"]
        mock_redis.xack.assert_any_call(
            aggregator_config.source_stream, aggregator_config.consumer_group, "100-0"
        )
        mock_redis.xack.assert_any_call(
            aggregator_config.source_stream, aggregator_config.consumer_group, "200-0"
        )

        assert calls[0]["streams"] == {aggregator_config.source_stream: "0"}
        assert calls[0]["consumername"] == "stable-consumer"

    async def test_consume_claims_orphaned_pending_via_xautoclaim(
        self, consumer: RedisConsumer, aggregator_config: AggregatorConfig
    ) -> None:
        """Entries orphaned by a dead (e.g. old random-uuid) consumer are
        claimed via XAUTOCLAIM with the configured idle threshold."""
        mock_redis = AsyncMock()

        claimed_message = (
            "300-0",
            {
                "symbol": "ORPHAN",
                "price": "30.0",
                "timestamp": "2024-01-15T09:32:00+00:00",
            },
        )

        xreadgroup_call_count = 0

        async def mock_xreadgroup(*args, **kwargs):
            nonlocal xreadgroup_call_count
            xreadgroup_call_count += 1
            if xreadgroup_call_count == 1:
                return []  # own PEL empty
            consumer._client = None
            return []

        xautoclaim_calls = []

        async def mock_xautoclaim(*args, **kwargs):
            xautoclaim_calls.append(kwargs)
            if len(xautoclaim_calls) == 1:
                return ("1234-0", [claimed_message], [])
            return ("0-0", [], [])

        mock_redis.xreadgroup = mock_xreadgroup
        mock_redis.xautoclaim = mock_xautoclaim
        mock_redis.xack = AsyncMock()
        consumer._client = mock_redis

        ticks = []
        async for tick in consumer.consume("stable-consumer"):
            ticks.append(tick)

        assert len(ticks) == 1
        assert ticks[0].symbol == "ORPHAN"
        mock_redis.xack.assert_any_call(
            aggregator_config.source_stream, aggregator_config.consumer_group, "300-0"
        )
        assert xautoclaim_calls[0]["min_idle_time"] == 60_000

    async def test_consume_handles_two_tuple_xautoclaim_response(
        self, consumer: RedisConsumer
    ) -> None:
        """Redis 6.2's XAUTOCLAIM returns a 2-tuple (no deleted-ids
        element); the recovery pass must not error unpacking it."""
        mock_redis = AsyncMock()

        async def mock_xreadgroup(*args, **kwargs):
            consumer._client = None
            return []

        mock_redis.xreadgroup = mock_xreadgroup
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", []))
        mock_redis.xack = AsyncMock()
        consumer._client = mock_redis

        ticks = []
        async for tick in consumer.consume("stable-consumer"):
            ticks.append(tick)

        assert ticks == []

    async def test_consume_pel_recovery_trimmed_entry_acked_not_yielded(
        self, consumer: RedisConsumer, aggregator_config: AggregatorConfig
    ) -> None:
        """A pending entry whose stream data was trimmed/deleted surfaces as
        data=None or data={} depending on server version; both must be acked
        and skipped, not yielded or raise."""
        mock_redis = AsyncMock()

        trimmed_message = (
            aggregator_config.source_stream,
            [("400-0", None), ("400-1", {})],
        )

        call_count = 0

        async def mock_xreadgroup(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [trimmed_message]
            consumer._client = None
            return []

        mock_redis.xreadgroup = mock_xreadgroup
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", [], []))
        mock_redis.xack = AsyncMock()
        consumer._client = mock_redis

        ticks = []
        async for tick in consumer.consume("stable-consumer"):
            ticks.append(tick)

        assert ticks == []
        assert consumer._parse_failures == 0
        mock_redis.xack.assert_any_call(
            aggregator_config.source_stream, aggregator_config.consumer_group, "400-0"
        )
        mock_redis.xack.assert_any_call(
            aggregator_config.source_stream, aggregator_config.consumer_group, "400-1"
        )

    async def test_consume_pel_recovery_unparseable_message_acked_and_counted(
        self, consumer: RedisConsumer, aggregator_config: AggregatorConfig
    ) -> None:
        """An unparseable message recovered from the PEL is acked, logged,
        and counted via _parse_failures, matching main-loop poison handling."""
        mock_redis = AsyncMock()

        poison_message = (
            aggregator_config.source_stream,
            [("500-0", {"invalid": "data"})],
        )

        call_count = 0

        async def mock_xreadgroup(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [poison_message]
            consumer._client = None
            return []

        mock_redis.xreadgroup = mock_xreadgroup
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", [], []))
        mock_redis.xack = AsyncMock()
        consumer._client = mock_redis

        ticks = []
        with structlog.testing.capture_logs() as cap_logs:
            async for tick in consumer.consume("stable-consumer"):
                ticks.append(tick)

        assert ticks == []
        events = [entry["event"] for entry in cap_logs]
        assert "unparseable_tick_message" in events
        mock_redis.xack.assert_any_call(
            aggregator_config.source_stream, aggregator_config.consumer_group, "500-0"
        )
        assert consumer._parse_failures == 1

    async def test_consume_empty_pel_proceeds_straight_to_fresh_read(
        self, consumer: RedisConsumer, aggregator_config: AggregatorConfig
    ) -> None:
        """When there is nothing to recover, consume() goes straight to
        reading fresh (">") messages."""
        mock_redis = AsyncMock()

        fresh_message = (
            aggregator_config.source_stream,
            [
                (
                    "600-0",
                    {
                        "symbol": "AAPL",
                        "price": "185.50",
                        "timestamp": "2024-01-15T09:30:00+00:00",
                    },
                )
            ],
        )

        calls = []

        async def mock_xreadgroup(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return []  # own PEL empty
            if len(calls) == 2:
                return [fresh_message]
            consumer._client = None
            return []

        mock_redis.xreadgroup = mock_xreadgroup
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", [], []))
        mock_redis.xack = AsyncMock()
        consumer._client = mock_redis

        ticks = []
        async for tick in consumer.consume("stable-consumer"):
            ticks.append(tick)

        assert len(ticks) == 1
        assert ticks[0].symbol == "AAPL"
        assert calls[0]["streams"] == {aggregator_config.source_stream: "0"}
        assert calls[1]["streams"] == {aggregator_config.source_stream: ">"}


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
        assert data["bb_upper"] == ""
        assert data["bb_lower"] == ""
        assert data["atr"] == ""

    async def test_publish_bar_with_bb_atr(self, publisher: BarPublisher) -> None:
        """BB and ATR fields are encoded into the Redis message."""
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

        await publisher.publish_bar(
            bar,
            interval="1m",
            bb_upper=190.0,
            bb_middle=185.0,
            bb_lower=180.0,
            atr=1.25,
        )

        data = mock_redis.xadd.call_args[0][1]
        assert data["bb_upper"] == "190.0"
        assert data["bb_middle"] == "185.0"
        assert data["bb_lower"] == "180.0"
        assert data["atr"] == "1.25"

    async def test_publish_bar_uses_stream_maxlen_by_default(
        self, publisher: BarPublisher
    ) -> None:
        """xadd is called with maxlen=100000, approximate=True by default."""
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

        call_kwargs = mock_redis.xadd.call_args[1]
        assert call_kwargs["maxlen"] == 100_000
        assert call_kwargs["approximate"] is True

    async def test_publish_bar_omits_maxlen_when_unlimited(self) -> None:
        """stream_maxlen=0 disables trimming: xadd is called without maxlen."""
        config = RedisConfig(host="localhost", port=6379, stream_maxlen=0)
        publisher = BarPublisher(config, bar_stream_prefix="stream:bars")
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

        call_kwargs = mock_redis.xadd.call_args[1]
        assert "maxlen" not in call_kwargs
        assert "approximate" not in call_kwargs

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
            id="$",
            mkstream=True,
        )

    async def test_connect_creates_group_with_configured_start_id(
        self, strategies_config: StrategiesConfig
    ) -> None:
        """consumer_group_start="0" (fulltest's replay setting) is passed
        through to xgroup_create (audit P1-8b)."""
        redis_config = RedisConfig(host="localhost", port=6379, consumer_group_start="0")
        consumer = BarConsumer(redis_config, strategies_config)
        mock_redis = AsyncMock()

        with patch(
            "axtrade.common.messaging.redis.Redis", return_value=mock_redis
        ):
            await consumer.connect()

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
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", [], []))
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
        assert result["bb_upper"] is None
        assert result["bb_middle"] is None
        assert result["bb_lower"] is None
        assert result["atr"] is None

    async def test_parse_bar_data_with_bb_atr(self, consumer: BarConsumer) -> None:
        """BB and ATR fields are decoded from the Redis message."""
        data = {
            "symbol": "AAPL",
            "open": "185.0",
            "high": "186.0",
            "low": "184.0",
            "close": "185.50",
            "volume": "10000",
            "timestamp": "2024-01-15T09:30:00+00:00",
            "bb_upper": "190.0",
            "bb_middle": "185.0",
            "bb_lower": "180.0",
            "atr": "1.25",
        }

        result = consumer._parse_bar_data(data)

        assert result is not None
        assert result["bb_upper"] == 190.0
        assert result["bb_middle"] == 185.0
        assert result["bb_lower"] == 180.0
        assert result["atr"] == 1.25

    async def test_parse_bar_data_invalid(self, consumer: BarConsumer) -> None:
        """Test parsing invalid bar data returns None."""
        data = {"invalid": "data"}

        result = consumer._parse_bar_data(data)

        assert result is None

    async def test_consume_acks_and_logs_poison_bar_message(
        self, consumer: BarConsumer, strategies_config: StrategiesConfig
    ) -> None:
        """An unparseable bar message must be acked and logged, and stream
        processing must continue past it."""
        mock_redis = AsyncMock()

        poison_message = (
            strategies_config.bar_stream,
            [("poison-0", {"invalid": "data"})],
        )
        good_message = (
            strategies_config.bar_stream,
            [
                (
                    "good-0",
                    {
                        "symbol": "AAPL",
                        "open": "185.0",
                        "high": "186.0",
                        "low": "184.0",
                        "close": "185.50",
                        "volume": "10000",
                        "timestamp": "2024-01-15T09:30:00+00:00",
                    },
                )
            ],
        )

        call_count = 0

        async def mock_xreadgroup(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [poison_message]
            if call_count == 2:
                return [good_message]
            consumer._client = None
            return []

        mock_redis.xreadgroup = mock_xreadgroup
        mock_redis.xack = AsyncMock()
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", [], []))
        consumer._client = mock_redis

        bars = []
        with structlog.testing.capture_logs() as cap_logs:
            async for bar_data in consumer.consume("test-consumer"):
                bars.append(bar_data)

        assert len(bars) == 1
        assert bars[0]["bar"].symbol == "AAPL"

        events = [entry["event"] for entry in cap_logs]
        assert "unparseable_bar_message" in events

        mock_redis.xack.assert_any_call(
            strategies_config.bar_stream, strategies_config.consumer_group, "poison-0"
        )
        mock_redis.xack.assert_any_call(
            strategies_config.bar_stream, strategies_config.consumer_group, "good-0"
        )

    def test_connected_property(self, consumer: BarConsumer) -> None:
        """Test connected property."""
        assert consumer.connected is False
        consumer._client = MagicMock()
        assert consumer.connected is True


def _bar_message_data(symbol: str, timestamp: str) -> dict:
    """Minimal valid bar message payload for PEL-recovery tests."""
    return {
        "symbol": symbol,
        "open": "185.0",
        "high": "186.0",
        "low": "184.0",
        "close": "185.50",
        "volume": "10000",
        "timestamp": timestamp,
    }


class TestBarConsumerPelRecovery:
    """Tests for the startup PEL-recovery pass in BarConsumer.consume()
    (audit P2-7)."""

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

    async def test_consume_replays_own_pending_before_fresh_messages(
        self, consumer: BarConsumer, strategies_config: StrategiesConfig
    ) -> None:
        """Messages already in this consumer's own PEL (delivered before a
        crash) are replayed before fresh (">") messages, and both are
        acked."""
        mock_redis = AsyncMock()

        pending_message = (
            strategies_config.bar_stream,
            [("100-0", _bar_message_data("PEND", "2024-01-15T09:30:00+00:00"))],
        )
        fresh_message = (
            strategies_config.bar_stream,
            [("200-0", _bar_message_data("FRESH", "2024-01-15T09:31:00+00:00"))],
        )

        calls = []

        async def mock_xreadgroup(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return [pending_message]
            if len(calls) == 2:
                return []  # own PEL drained
            if len(calls) == 3:
                return [fresh_message]
            consumer._client = None
            return []

        mock_redis.xreadgroup = mock_xreadgroup
        mock_redis.xack = AsyncMock()
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", [], []))
        consumer._client = mock_redis

        bars = []
        async for bar_data in consumer.consume("stable-consumer"):
            bars.append(bar_data)

        assert [b["bar"].symbol for b in bars] == ["PEND", "FRESH"]
        mock_redis.xack.assert_any_call(
            strategies_config.bar_stream, strategies_config.consumer_group, "100-0"
        )
        mock_redis.xack.assert_any_call(
            strategies_config.bar_stream, strategies_config.consumer_group, "200-0"
        )

        assert calls[0]["streams"] == {strategies_config.bar_stream: "0"}
        assert calls[0]["consumername"] == "stable-consumer"

    async def test_consume_claims_orphaned_pending_via_xautoclaim(
        self, consumer: BarConsumer, strategies_config: StrategiesConfig
    ) -> None:
        """Entries orphaned by a dead (e.g. old random-uuid) consumer are
        claimed via XAUTOCLAIM with the configured idle threshold."""
        mock_redis = AsyncMock()

        claimed_message = (
            "300-0",
            _bar_message_data("ORPHAN", "2024-01-15T09:32:00+00:00"),
        )

        xreadgroup_call_count = 0

        async def mock_xreadgroup(*args, **kwargs):
            nonlocal xreadgroup_call_count
            xreadgroup_call_count += 1
            if xreadgroup_call_count == 1:
                return []  # own PEL empty
            consumer._client = None
            return []

        xautoclaim_calls = []

        async def mock_xautoclaim(*args, **kwargs):
            xautoclaim_calls.append(kwargs)
            if len(xautoclaim_calls) == 1:
                return ("1234-0", [claimed_message], [])
            return ("0-0", [], [])

        mock_redis.xreadgroup = mock_xreadgroup
        mock_redis.xautoclaim = mock_xautoclaim
        mock_redis.xack = AsyncMock()
        consumer._client = mock_redis

        bars = []
        async for bar_data in consumer.consume("stable-consumer"):
            bars.append(bar_data)

        assert len(bars) == 1
        assert bars[0]["bar"].symbol == "ORPHAN"
        mock_redis.xack.assert_any_call(
            strategies_config.bar_stream, strategies_config.consumer_group, "300-0"
        )
        assert xautoclaim_calls[0]["min_idle_time"] == 60_000

    async def test_consume_handles_two_tuple_xautoclaim_response(
        self, consumer: BarConsumer
    ) -> None:
        """Redis 6.2's XAUTOCLAIM returns a 2-tuple (no deleted-ids
        element); the recovery pass must not error unpacking it."""
        mock_redis = AsyncMock()

        async def mock_xreadgroup(*args, **kwargs):
            consumer._client = None
            return []

        mock_redis.xreadgroup = mock_xreadgroup
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", []))
        mock_redis.xack = AsyncMock()
        consumer._client = mock_redis

        bars = []
        async for bar_data in consumer.consume("stable-consumer"):
            bars.append(bar_data)

        assert bars == []

    async def test_consume_pel_recovery_trimmed_entry_acked_not_yielded(
        self, consumer: BarConsumer, strategies_config: StrategiesConfig
    ) -> None:
        """A pending entry whose stream data was trimmed/deleted surfaces as
        data=None or data={} depending on server version; both must be acked
        and skipped, not yielded or raise."""
        mock_redis = AsyncMock()

        trimmed_message = (
            strategies_config.bar_stream,
            [("400-0", None), ("400-1", {})],
        )

        call_count = 0

        async def mock_xreadgroup(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [trimmed_message]
            consumer._client = None
            return []

        mock_redis.xreadgroup = mock_xreadgroup
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", [], []))
        mock_redis.xack = AsyncMock()
        consumer._client = mock_redis

        bars = []
        async for bar_data in consumer.consume("stable-consumer"):
            bars.append(bar_data)

        assert bars == []
        assert consumer._parse_failures == 0
        mock_redis.xack.assert_any_call(
            strategies_config.bar_stream, strategies_config.consumer_group, "400-0"
        )
        mock_redis.xack.assert_any_call(
            strategies_config.bar_stream, strategies_config.consumer_group, "400-1"
        )

    async def test_consume_pel_recovery_unparseable_message_acked_and_counted(
        self, consumer: BarConsumer, strategies_config: StrategiesConfig
    ) -> None:
        """An unparseable message recovered from the PEL is acked, logged,
        and counted via _parse_failures, matching main-loop poison handling."""
        mock_redis = AsyncMock()

        poison_message = (
            strategies_config.bar_stream,
            [("500-0", {"invalid": "data"})],
        )

        call_count = 0

        async def mock_xreadgroup(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [poison_message]
            consumer._client = None
            return []

        mock_redis.xreadgroup = mock_xreadgroup
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", [], []))
        mock_redis.xack = AsyncMock()
        consumer._client = mock_redis

        bars = []
        with structlog.testing.capture_logs() as cap_logs:
            async for bar_data in consumer.consume("stable-consumer"):
                bars.append(bar_data)

        assert bars == []
        events = [entry["event"] for entry in cap_logs]
        assert "unparseable_bar_message" in events
        mock_redis.xack.assert_any_call(
            strategies_config.bar_stream, strategies_config.consumer_group, "500-0"
        )
        assert consumer._parse_failures == 1

    async def test_consume_empty_pel_proceeds_straight_to_fresh_read(
        self, consumer: BarConsumer, strategies_config: StrategiesConfig
    ) -> None:
        """When there is nothing to recover, consume() goes straight to
        reading fresh (">") messages."""
        mock_redis = AsyncMock()

        fresh_message = (
            strategies_config.bar_stream,
            [("600-0", _bar_message_data("AAPL", "2024-01-15T09:30:00+00:00"))],
        )

        calls = []

        async def mock_xreadgroup(*args, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return []  # own PEL empty
            if len(calls) == 2:
                return [fresh_message]
            consumer._client = None
            return []

        mock_redis.xreadgroup = mock_xreadgroup
        mock_redis.xautoclaim = AsyncMock(return_value=("0-0", [], []))
        mock_redis.xack = AsyncMock()
        consumer._client = mock_redis

        bars = []
        async for bar_data in consumer.consume("stable-consumer"):
            bars.append(bar_data)

        assert len(bars) == 1
        assert bars[0]["bar"].symbol == "AAPL"
        assert calls[0]["streams"] == {strategies_config.bar_stream: "0"}
        assert calls[1]["streams"] == {strategies_config.bar_stream: ">"}
