"""Strategy runtime control - state persistence and IPC."""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as redis

from axtrade.common import DatabasePool, RedisConfig, StrategiesConfig, get_logger


@dataclass
class StrategyState:
    """Persisted strategy state."""

    strategy_id: str
    enabled: bool
    updated_at: datetime


@dataclass
class ControlCommand:
    """Control command from API to StrategyRunner."""

    action: str  # "enable" or "disable"
    strategy_id: str
    timestamp: datetime


class StrategyStateRepository:
    """Repository for strategy state persistence."""

    def __init__(self, pool: DatabasePool):
        self.pool = pool
        self.logger = get_logger("strategy_state")

    async def get(self, strategy_id: str) -> Optional[StrategyState]:
        """Get state for a strategy."""
        query = """
            SELECT strategy_id, enabled, updated_at
            FROM strategy_state
            WHERE strategy_id = $1
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, strategy_id)

        if not row:
            return None

        return StrategyState(
            strategy_id=row["strategy_id"],
            enabled=row["enabled"],
            updated_at=row["updated_at"],
        )

    async def get_all(self) -> list[StrategyState]:
        """Get all strategy states."""
        query = """
            SELECT strategy_id, enabled, updated_at
            FROM strategy_state
            ORDER BY strategy_id
        """
        async with self.pool.acquire() as conn:
            rows = await conn.fetch(query)

        return [
            StrategyState(
                strategy_id=row["strategy_id"],
                enabled=row["enabled"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    async def set_state(self, strategy_id: str, enabled: bool) -> StrategyState:
        """Set strategy enabled state (upsert)."""
        query = """
            INSERT INTO strategy_state (strategy_id, enabled, updated_at)
            VALUES ($1, $2, NOW())
            ON CONFLICT (strategy_id)
            DO UPDATE SET enabled = EXCLUDED.enabled, updated_at = NOW()
            RETURNING strategy_id, enabled, updated_at
        """
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(query, strategy_id, enabled)

        self.logger.info(
            "Set strategy state",
            strategy_id=strategy_id,
            enabled=enabled,
        )

        return StrategyState(
            strategy_id=row["strategy_id"],
            enabled=row["enabled"],
            updated_at=row["updated_at"],
        )

    async def delete(self, strategy_id: str) -> bool:
        """Delete strategy state."""
        query = "DELETE FROM strategy_state WHERE strategy_id = $1"
        async with self.pool.acquire() as conn:
            result = await conn.execute(query, strategy_id)

        return result == "DELETE 1"


class StrategyControlPublisher:
    """Publishes control commands via Redis pub/sub."""

    def __init__(self, config: RedisConfig, strategies_config: StrategiesConfig):
        self.config = config
        self.channel = strategies_config.control_channel
        self._client: Optional[redis.Redis] = None
        self.logger = get_logger("strategy_control_pub")

    async def connect(self) -> None:
        """Connect to Redis."""
        self._client = redis.Redis(
            host=self.config.host,
            port=self.config.port,
            decode_responses=True,
        )
        await self._client.ping()
        self.logger.info("Connected to Redis for control publishing")

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def publish(self, command: ControlCommand) -> int:
        """Publish a control command.

        Args:
            command: Control command to publish

        Returns:
            Number of subscribers that received the message
        """
        if not self._client:
            raise RuntimeError("Not connected to Redis")

        message = json.dumps({
            "action": command.action,
            "strategy_id": command.strategy_id,
            "timestamp": command.timestamp.isoformat(),
        })

        result = await self._client.publish(self.channel, message)
        self.logger.info(
            "Published control command",
            action=command.action,
            strategy_id=command.strategy_id,
            subscribers=result,
        )
        return result

    async def enable(self, strategy_id: str) -> int:
        """Publish enable command."""
        return await self.publish(ControlCommand(
            action="enable",
            strategy_id=strategy_id,
            timestamp=datetime.now(timezone.utc),
        ))

    async def disable(self, strategy_id: str) -> int:
        """Publish disable command."""
        return await self.publish(ControlCommand(
            action="disable",
            strategy_id=strategy_id,
            timestamp=datetime.now(timezone.utc),
        ))


class StrategyControlSubscriber:
    """Subscribes to control commands via Redis pub/sub."""

    def __init__(self, config: RedisConfig, strategies_config: StrategiesConfig):
        self.config = config
        self.channel = strategies_config.control_channel
        self._client: Optional[redis.Redis] = None
        self._pubsub: Optional[redis.client.PubSub] = None
        self.logger = get_logger("strategy_control_sub")

    async def connect(self) -> None:
        """Connect to Redis and subscribe to control channel."""
        self._client = redis.Redis(
            host=self.config.host,
            port=self.config.port,
            decode_responses=True,
        )
        await self._client.ping()

        self._pubsub = self._client.pubsub()
        await self._pubsub.subscribe(self.channel)
        self.logger.info("Subscribed to control channel", channel=self.channel)

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._pubsub:
            await self._pubsub.unsubscribe(self.channel)
            await self._pubsub.aclose()
            self._pubsub = None

        if self._client:
            await self._client.aclose()
            self._client = None

    async def subscribe(self) -> AsyncIterator[ControlCommand]:
        """Subscribe and yield control commands.

        Yields:
            ControlCommand objects as they are received
        """
        if not self._pubsub:
            raise RuntimeError("Not connected to Redis")

        while True:
            try:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=1.0,
                )
                if message is None:
                    await asyncio.sleep(0.1)
                    continue

                if message["type"] != "message":
                    continue

                data = json.loads(message["data"])
                command = ControlCommand(
                    action=data["action"],
                    strategy_id=data["strategy_id"],
                    timestamp=datetime.fromisoformat(data["timestamp"]),
                )
                yield command

            except asyncio.CancelledError:
                break
            except json.JSONDecodeError as e:
                self.logger.warning("Invalid control message", error=str(e))
            except Exception as e:
                self.logger.error("Error in control subscriber", error=str(e))
                await asyncio.sleep(1.0)
