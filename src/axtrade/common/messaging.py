"""Redis messaging helpers."""

from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as redis

from .config import AggregatorConfig, RedisConfig, StrategiesConfig
from .types import Bar, Tick


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
        message_id = await self._client.xadd(stream_key, tick.to_dict())
        return message_id

    async def publish_tick_batch(
        self, ticks: list[Tick], market: str = "us"
    ) -> list[str]:
        """Publish multiple ticks using a Redis pipeline.

        Args:
            ticks: List of ticks to publish
            market: Market identifier

        Returns:
            List of stream message IDs
        """
        if not self._client:
            raise RuntimeError("Not connected to Redis")
        if not ticks:
            return []

        stream_key = f"{self.config.stream_prefix}:{market}"
        async with self._client.pipeline(transaction=False) as pipe:
            for tick in ticks:
                pipe.xadd(stream_key, tick.to_dict())
            results = await pipe.execute()
        return results

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
                stream_key, group, id="0", mkstream=True
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

            batch_ids = []
            for stream_name, stream_messages in messages:
                for msg_id, data in stream_messages:
                    tick = self._parse_tick(data)
                    if tick:
                        batch_ids.append(msg_id)
                        yield tick
            if batch_ids and self._client:
                await self._client.xack(stream_key, group, *batch_ids)

    def _parse_tick(self, data: dict) -> Optional[Tick]:
        """Parse tick data from Redis message."""
        try:
            timestamp_str = data.get("timestamp", "")
            if timestamp_str:
                timestamp = datetime.fromisoformat(timestamp_str)
            else:
                timestamp = datetime.now(timezone.utc)

            volume = data.get("volume", "")
            volume_int = int(volume) if volume else None

            bid = data.get("bid", "")
            bid_float = float(bid) if bid else None

            ask = data.get("ask", "")
            ask_float = float(ask) if ask else None

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
        # Add regime data
        data["regime"] = regime if regime else ""
        data["trend"] = trend if trend else ""
        data["volatility"] = volatility if volatility else ""
        data["trend_strength"] = str(trend_strength) if trend_strength is not None else ""
        data["volatility_percentile"] = str(volatility_percentile) if volatility_percentile is not None else ""
        message_id = await self._client.xadd(stream_key, data)
        return message_id

    async def publish_bar_batch(
        self,
        bars_with_indicators: list[tuple[Bar, str, str, dict]],
    ) -> list[str]:
        """Publish multiple bars using a Redis pipeline.

        Args:
            bars_with_indicators: List of (bar, interval, market, indicators_dict) tuples.
                indicators_dict keys: sma_20, rsi_14, regime, trend, volatility,
                trend_strength, volatility_percentile.

        Returns:
            List of stream message IDs
        """
        if not self._client:
            raise RuntimeError("Not connected to Redis")
        if not bars_with_indicators:
            return []

        async with self._client.pipeline(transaction=False) as pipe:
            for bar, interval, market, indicators in bars_with_indicators:
                stream_key = f"{self.bar_stream_prefix}:{interval}:{market}"
                data = bar.to_dict()
                data["sma_20"] = str(indicators.get("sma_20", "")) if indicators.get("sma_20") is not None else ""
                data["rsi_14"] = str(indicators.get("rsi_14", "")) if indicators.get("rsi_14") is not None else ""
                data["regime"] = indicators.get("regime") or ""
                data["trend"] = indicators.get("trend") or ""
                data["volatility"] = indicators.get("volatility") or ""
                data["trend_strength"] = str(indicators.get("trend_strength", "")) if indicators.get("trend_strength") is not None else ""
                data["volatility_percentile"] = str(indicators.get("volatility_percentile", "")) if indicators.get("volatility_percentile") is not None else ""
                pipe.xadd(stream_key, data)
            results = await pipe.execute()
        return results

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
                stream_key, group, id="0", mkstream=True
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

            batch_ids = []
            for stream_name, stream_messages in messages:
                for msg_id, data in stream_messages:
                    bar_data = self._parse_bar_data(data)
                    if bar_data:
                        batch_ids.append(msg_id)
                        yield bar_data
            if batch_ids and self._client:
                await self._client.xack(stream_key, group, *batch_ids)

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
