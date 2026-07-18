"""Redis messaging helpers."""

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as redis

from .config import AggregatorConfig, RedisConfig, StrategiesConfig
from .logging import get_logger
from .types import Bar, Tick

logger = get_logger(__name__)

# Orphaned-message claim threshold: how long a message must sit unacked in
# another consumer's PEL before we steal it via XAUTOCLAIM. Protects a live
# sibling consumer (still working the message) from having it stolen out
# from under it.
CLAIM_MIN_IDLE_MS = 60_000


async def _recover_pending(
    client: redis.Redis,
    stream_key: str,
    group: str,
    consumer_name: str,
    min_idle_ms: int = CLAIM_MIN_IDLE_MS,
) -> AsyncIterator[tuple[str, Optional[dict]]]:
    """Replay entries left pending by a crashed/restarted consumer.

    Two phases, run once at the start of consume():

    1. Drain this consumer's own PEL - messages that were delivered to this
       stable consumer name before a crash, regardless of idle time.
    2. Claim orphaned entries idle longer than `min_idle_ms` from other
       (e.g. dead random-uuid) consumers in the group.

    Yields (msg_id, data) pairs. `data` is None or empty (varies by server
    version) when the stream entry was trimmed/deleted while still pending -
    callers should just ack and skip it.
    """
    own_pending = 0
    claimed_total = 0
    trimmed = 0

    # Phase 1: drain this consumer's own PEL. Reading with an explicit id
    # (not ">") returns only already-delivered entries and never blocks.
    cursor = "0"
    while True:
        try:
            messages = await client.xreadgroup(
                groupname=group,
                consumername=consumer_name,
                streams={stream_key: cursor},
                count=100,
            )
        except (AttributeError, ConnectionError):
            return

        if not messages:
            break

        stream_messages = messages[0][1]
        if not stream_messages:
            break

        for msg_id, data in stream_messages:
            own_pending += 1
            if not data:
                trimmed += 1
            yield msg_id, data
            # Advance the cursor (not the caller's acks) so this loop
            # terminates even if the caller never acks.
            cursor = msg_id

    # Phase 2: claim orphans from dead consumers (e.g. old random-uuid names).
    cursor = "0-0"
    while True:
        try:
            result = await client.xautoclaim(
                stream_key,
                group,
                consumer_name,
                min_idle_time=min_idle_ms,
                start_id=cursor,
                count=100,
            )
        except (AttributeError, ConnectionError):
            return

        # Redis >=7.0 returns a third element (deleted ids); Redis 6.2
        # returns two. Only the first two are ever needed here.
        next_cursor, claimed = result[0], result[1]
        for msg_id, data in claimed:
            claimed_total += 1
            if not data:
                trimmed += 1
            yield msg_id, data

        if next_cursor == "0-0":
            break
        if not claimed and next_cursor == cursor:
            # Belt-and-braces guard against a non-advancing server/mock.
            break
        cursor = next_cursor

    log = logger.info if (own_pending or claimed_total or trimmed) else logger.debug
    log(
        "pel_recovery_complete",
        stream=stream_key,
        consumer=consumer_name,
        own_pending=own_pending,
        claimed=claimed_total,
        trimmed=trimmed,
    )


class RedisPublisher:
    """Publishes messages to Redis Streams."""

    def __init__(self, config: RedisConfig):
        """Initialize Redis publisher.

        Args:
            config: Redis configuration
        """
        self.config = config
        self._client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Connect to Redis."""
        self._client = redis.Redis(
            host=self.config.host,
            port=self.config.port,
            db=self.config.db,
            decode_responses=True,
        )
        await self._client.ping()

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def publish_tick(self, tick: Tick, market: str = "us") -> str:
        """Publish a tick to Redis Stream.

        Args:
            tick: Tick data to publish
            market: Market identifier (us, eu, etc.)

        Returns:
            Stream message ID
        """
        if not self._client:
            raise RuntimeError("Not connected to Redis")

        stream_key = f"{self.config.stream_prefix}:{market}"
        if self.config.stream_maxlen:
            message_id = await self._client.xadd(
                stream_key,
                tick.to_dict(),
                maxlen=self.config.stream_maxlen,
                approximate=True,
            )
        else:
            message_id = await self._client.xadd(stream_key, tick.to_dict())
        return message_id

    @property
    def connected(self) -> bool:
        """Check if connected to Redis."""
        return self._client is not None


class RedisConsumer:
    """Consumes messages from Redis Streams using consumer groups."""

    def __init__(self, config: RedisConfig, aggregator_config: AggregatorConfig):
        """Initialize Redis consumer.

        Args:
            config: Redis configuration
            aggregator_config: Aggregator configuration
        """
        self.config = config
        self.aggregator_config = aggregator_config
        self._client: Optional[redis.Redis] = None
        self._parse_failures = 0

    async def connect(self) -> None:
        """Connect to Redis and create consumer group if needed."""
        self._client = redis.Redis(
            host=self.config.host,
            port=self.config.port,
            db=self.config.db,
            decode_responses=True,
        )
        await self._client.ping()

        # Create consumer group if it doesn't exist
        stream_key = self.aggregator_config.source_stream
        group = self.aggregator_config.consumer_group
        try:
            await self._client.xgroup_create(
                stream_key, group, id=self.config.consumer_group_start, mkstream=True
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def consume(
        self, consumer_name: str, block_ms: int = 1000
    ) -> AsyncIterator[Tick]:
        """Consume ticks from Redis stream.

        Args:
            consumer_name: Unique name for this consumer instance
            block_ms: Milliseconds to block waiting for messages

        Yields:
            Tick objects from the stream
        """
        if not self._client:
            raise RuntimeError("Not connected to Redis")

        stream_key = self.aggregator_config.source_stream
        group = self.aggregator_config.consumer_group

        async for msg_id, data in _recover_pending(
            self._client, stream_key, group, consumer_name
        ):
            if not data:
                if self._client:
                    await self._client.xack(stream_key, group, msg_id)
                continue
            tick = self._parse_tick(data)
            if tick:
                yield tick
                if self._client:
                    await self._client.xack(stream_key, group, msg_id)
            else:
                self._parse_failures += 1
                logger.warning(
                    "unparseable_tick_message",
                    data=data,
                    parse_failures_total=self._parse_failures,
                )
                if self._client:
                    await self._client.xack(stream_key, group, msg_id)

        while True:
            if not self._client:
                return

            try:
                messages = await self._client.xreadgroup(
                    groupname=group,
                    consumername=consumer_name,
                    streams={stream_key: ">"},
                    count=100,
                    block=block_ms,
                )
            except (AttributeError, ConnectionError):
                return

            if not messages:
                continue

            for stream_name, stream_messages in messages:
                for msg_id, data in stream_messages:
                    tick = self._parse_tick(data)
                    if tick:
                        yield tick
                        if self._client:
                            await self._client.xack(stream_key, group, msg_id)
                    else:
                        self._parse_failures += 1
                        logger.warning(
                            "unparseable_tick_message",
                            data=data,
                            parse_failures_total=self._parse_failures,
                        )
                        if self._client:
                            await self._client.xack(stream_key, group, msg_id)

    def _parse_tick(self, data: dict) -> Optional[Tick]:
        """Parse tick data from Redis message."""
        try:
            timestamp_str = data.get("timestamp", "")
            if timestamp_str:
                timestamp = datetime.fromisoformat(timestamp_str)
            else:
                timestamp = datetime.now(timezone.utc)

            volume = data.get("volume", "")
            # ib_insync's Ticker.volume is a float (e.g. "2417.0"); go through
            # float() first so cumulative-day-volume style values still parse.
            volume_int = int(float(volume)) if volume != "" else None

            bid = data.get("bid", "")
            bid_float = float(bid) if bid != "" else None

            ask = data.get("ask", "")
            ask_float = float(ask) if ask != "" else None

            return Tick(
                symbol=data["symbol"],
                price=float(data["price"]),
                timestamp=timestamp,
                bid=bid_float,
                ask=ask_float,
                volume=volume_int,
            )
        except (KeyError, ValueError):
            return None

    @property
    def connected(self) -> bool:
        """Check if connected to Redis."""
        return self._client is not None


class BarPublisher:
    """Publishes bars to Redis Streams."""

    def __init__(self, config: RedisConfig, bar_stream_prefix: str = "stream:bars"):
        """Initialize bar publisher.

        Args:
            config: Redis configuration
            bar_stream_prefix: Prefix for bar streams
        """
        self.config = config
        self.bar_stream_prefix = bar_stream_prefix
        self._client: Optional[redis.Redis] = None

    async def connect(self) -> None:
        """Connect to Redis."""
        self._client = redis.Redis(
            host=self.config.host,
            port=self.config.port,
            db=self.config.db,
            decode_responses=True,
        )
        await self._client.ping()

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def publish_bar(
        self,
        bar: Bar,
        interval: str,
        market: str = "us",
        sma_20: Optional[float] = None,
        rsi_14: Optional[float] = None,
        bb_upper: Optional[float] = None,
        bb_middle: Optional[float] = None,
        bb_lower: Optional[float] = None,
        atr: Optional[float] = None,
        regime: Optional[str] = None,
        trend: Optional[str] = None,
        volatility: Optional[str] = None,
        trend_strength: Optional[float] = None,
        volatility_percentile: Optional[float] = None,
    ) -> str:
        """Publish a bar to Redis Stream.

        Args:
            bar: Bar data to publish
            interval: Bar interval (1m, 5m, etc.)
            market: Market identifier
            sma_20: SMA indicator value
            rsi_14: RSI indicator value
            bb_upper/bb_middle/bb_lower: Bollinger Band values
            atr: Average True Range value
            regime: Market regime classification
            trend: Market trend direction
            volatility: Volatility state
            trend_strength: Trend strength 0-100
            volatility_percentile: Volatility percentile 0-100

        Returns:
            Stream message ID
        """
        if not self._client:
            raise RuntimeError("Not connected to Redis")

        stream_key = f"{self.bar_stream_prefix}:{interval}:{market}"
        data = bar.to_dict()
        # Add indicators to message
        data["sma_20"] = str(sma_20) if sma_20 is not None else ""
        data["rsi_14"] = str(rsi_14) if rsi_14 is not None else ""
        data["bb_upper"] = str(bb_upper) if bb_upper is not None else ""
        data["bb_middle"] = str(bb_middle) if bb_middle is not None else ""
        data["bb_lower"] = str(bb_lower) if bb_lower is not None else ""
        data["atr"] = str(atr) if atr is not None else ""
        # Add regime data
        data["regime"] = regime if regime else ""
        data["trend"] = trend if trend else ""
        data["volatility"] = volatility if volatility else ""
        data["trend_strength"] = str(trend_strength) if trend_strength is not None else ""
        data["volatility_percentile"] = str(volatility_percentile) if volatility_percentile is not None else ""
        if self.config.stream_maxlen:
            message_id = await self._client.xadd(
                stream_key, data, maxlen=self.config.stream_maxlen, approximate=True
            )
        else:
            message_id = await self._client.xadd(stream_key, data)
        return message_id

    @property
    def connected(self) -> bool:
        """Check if connected to Redis."""
        return self._client is not None


class BarConsumer:
    """Consumes bars from Redis Streams for strategy processing."""

    def __init__(self, config: RedisConfig, strategies_config: StrategiesConfig):
        """Initialize bar consumer.

        Args:
            config: Redis configuration
            strategies_config: Strategies configuration
        """
        self.config = config
        self.strategies_config = strategies_config
        self._client: Optional[redis.Redis] = None
        self._parse_failures = 0

    async def connect(self) -> None:
        """Connect to Redis and create consumer group if needed."""
        self._client = redis.Redis(
            host=self.config.host,
            port=self.config.port,
            db=self.config.db,
            decode_responses=True,
        )
        await self._client.ping()

        # Create consumer group if it doesn't exist
        stream_key = self.strategies_config.bar_stream
        group = self.strategies_config.consumer_group
        try:
            await self._client.xgroup_create(
                stream_key, group, id=self.config.consumer_group_start, mkstream=True
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def consume(
        self, consumer_name: str, block_ms: int = 1000
    ) -> AsyncIterator[dict]:
        """Consume bars from Redis stream.

        Args:
            consumer_name: Unique name for this consumer instance
            block_ms: Milliseconds to block waiting for messages

        Yields:
            Dict with bar and indicator data
        """
        if not self._client:
            raise RuntimeError("Not connected to Redis")

        stream_key = self.strategies_config.bar_stream
        group = self.strategies_config.consumer_group

        async for msg_id, data in _recover_pending(
            self._client, stream_key, group, consumer_name
        ):
            if not data:
                if self._client:
                    await self._client.xack(stream_key, group, msg_id)
                continue
            bar_data = self._parse_bar_data(data)
            if bar_data:
                yield bar_data
                if self._client:
                    await self._client.xack(stream_key, group, msg_id)
            else:
                self._parse_failures += 1
                logger.warning(
                    "unparseable_bar_message",
                    data=data,
                    parse_failures_total=self._parse_failures,
                )
                if self._client:
                    await self._client.xack(stream_key, group, msg_id)

        while True:
            if not self._client:
                return

            try:
                messages = await self._client.xreadgroup(
                    groupname=group,
                    consumername=consumer_name,
                    streams={stream_key: ">"},
                    count=100,
                    block=block_ms,
                )
            except (AttributeError, ConnectionError):
                return

            if not messages:
                continue

            for stream_name, stream_messages in messages:
                for msg_id, data in stream_messages:
                    bar_data = self._parse_bar_data(data)
                    if bar_data:
                        yield bar_data
                        if self._client:
                            await self._client.xack(stream_key, group, msg_id)
                    else:
                        self._parse_failures += 1
                        logger.warning(
                            "unparseable_bar_message",
                            data=data,
                            parse_failures_total=self._parse_failures,
                        )
                        if self._client:
                            await self._client.xack(stream_key, group, msg_id)

    def _parse_bar_data(self, data: dict) -> Optional[dict]:
        """Parse bar data from Redis message."""
        try:
            timestamp_str = data.get("timestamp", "")
            if timestamp_str:
                timestamp = datetime.fromisoformat(timestamp_str)
            else:
                timestamp = datetime.now(timezone.utc)

            bar = Bar(
                symbol=data["symbol"],
                open=float(data["open"]),
                high=float(data["high"]),
                low=float(data["low"]),
                close=float(data["close"]),
                volume=int(data["volume"]),
                timestamp=timestamp,
            )

            return {
                "bar": bar,
                "sma_20": float(data["sma_20"]) if data.get("sma_20") else None,
                "rsi_14": float(data["rsi_14"]) if data.get("rsi_14") else None,
                "bb_upper": float(data["bb_upper"]) if data.get("bb_upper") else None,
                "bb_middle": float(data["bb_middle"]) if data.get("bb_middle") else None,
                "bb_lower": float(data["bb_lower"]) if data.get("bb_lower") else None,
                "atr": float(data["atr"]) if data.get("atr") else None,
                "regime": data.get("regime") or None,
                "trend": data.get("trend") or None,
                "volatility": data.get("volatility") or None,
                "trend_strength": float(data["trend_strength"]) if data.get("trend_strength") else None,
                "volatility_percentile": float(data["volatility_percentile"]) if data.get("volatility_percentile") else None,
            }
        except (KeyError, ValueError):
            return None

    @property
    def connected(self) -> bool:
        """Check if connected to Redis."""
        return self._client is not None
