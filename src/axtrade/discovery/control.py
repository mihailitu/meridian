"""Discovery runtime control - IPC for triggering scans and managing manual symbols.

Mirrors strategies/control.py's publisher/subscriber structure. The API
process no longer runs a DiscoveryRunner (audit P1-3: scanning moved to the
strategy-runner process to match fulltest's in-process wiring), so mutating
discovery endpoints publish commands here instead of calling DiscoveryService
directly.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as redis

from axtrade.common import DiscoveryConfig, RedisConfig, get_logger


@dataclass
class DiscoveryControlCommand:
    """Control command from the API to the discovery scanner (DiscoveryRunner)."""

    command: str  # "scan", "add_symbols", or "remove_symbols"
    symbols: list[dict] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class DiscoveryControlPublisher:
    """Publishes discovery control commands via Redis pub/sub."""

    def __init__(self, config: RedisConfig, discovery_config: DiscoveryConfig):
        self.config = config
        self.channel = discovery_config.control_channel
        self._client: Optional[redis.Redis] = None
        self.logger = get_logger("discovery_control_pub")

    async def connect(self) -> None:
        """Connect to Redis."""
        self._client = redis.Redis(
            host=self.config.host,
            port=self.config.port,
            db=self.config.db,
            decode_responses=True,
        )
        await self._client.ping()
        self.logger.info("Connected to Redis for discovery control publishing")

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def publish(self, command: DiscoveryControlCommand) -> int:
        """Publish a discovery control command.

        Returns:
            Number of subscribers that received the message
        """
        if not self._client:
            raise RuntimeError("Not connected to Redis")

        message = json.dumps({
            "command": command.command,
            "symbols": command.symbols,
            "timestamp": command.timestamp.isoformat(),
        })

        result = await self._client.publish(self.channel, message)
        self.logger.info(
            "Published discovery control command",
            command=command.command,
            subscribers=result,
        )
        return result

    async def scan(self) -> int:
        """Publish a command to trigger an immediate scan."""
        return await self.publish(DiscoveryControlCommand(command="scan"))

    async def add_symbols(self, symbols: list[dict]) -> int:
        """Publish a command to add symbols manually.

        Args:
            symbols: List of dicts with "symbol", and optionally "price"/"notes".
        """
        return await self.publish(DiscoveryControlCommand(command="add_symbols", symbols=symbols))

    async def remove_symbols(self, symbols: Optional[list[dict]] = None) -> int:
        """Publish a command to remove (clear) discovered symbols.

        DiscoveryService has no per-symbol removal path today, only
        clear_discovered() -- matching the pre-existing DELETE /discovery/symbols
        behavior, which has always cleared everything rather than removing
        individual symbols.
        """
        return await self.publish(
            DiscoveryControlCommand(command="remove_symbols", symbols=symbols or [])
        )


class DiscoveryControlSubscriber:
    """Subscribes to discovery control commands via Redis pub/sub."""

    def __init__(self, config: RedisConfig, discovery_config: DiscoveryConfig):
        self.config = config
        self.channel = discovery_config.control_channel
        self._client: Optional[redis.Redis] = None
        self._pubsub: Optional[redis.client.PubSub] = None
        self.logger = get_logger("discovery_control_sub")

    async def connect(self) -> None:
        """Connect to Redis and subscribe to the control channel."""
        self._client = redis.Redis(
            host=self.config.host,
            port=self.config.port,
            db=self.config.db,
            decode_responses=True,
        )
        await self._client.ping()

        self._pubsub = self._client.pubsub()
        await self._pubsub.subscribe(self.channel)
        self.logger.info("Subscribed to discovery control channel", channel=self.channel)

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._pubsub:
            await self._pubsub.unsubscribe(self.channel)
            await self._pubsub.aclose()
            self._pubsub = None

        if self._client:
            await self._client.aclose()
            self._client = None

    async def subscribe(self) -> AsyncIterator[DiscoveryControlCommand]:
        """Subscribe and yield discovery control commands."""
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
                command = DiscoveryControlCommand(
                    command=data["command"],
                    symbols=data.get("symbols", []),
                    timestamp=datetime.fromisoformat(data["timestamp"]),
                )
                yield command

            except asyncio.CancelledError:
                break
            except json.JSONDecodeError as e:
                self.logger.warning("Invalid discovery control message", error=str(e))
            except Exception as e:
                self.logger.error("Error in discovery control subscriber", error=str(e))
                await asyncio.sleep(1.0)
