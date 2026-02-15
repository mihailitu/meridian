"""Gateway runtime control - dynamic symbol subscription via Redis pub/sub."""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as redis

from axtrade.common import GatewayConfig, RedisConfig, SymbolConfig, get_logger


@dataclass
class GatewayControlCommand:
    """Control command for the gateway service."""

    action: str  # "add_symbols" or "remove_symbols"
    symbols: list[dict]  # List of symbol dicts (with "symbol" and optionally "base_price")
    timestamp: datetime


class GatewayControlPublisher:
    """Publishes gateway control commands via Redis pub/sub."""

    def __init__(self, config: RedisConfig, gateway_config: GatewayConfig):
        self.config = config
        self.channel = gateway_config.control_channel
        self._client: Optional[redis.Redis] = None
        self.logger = get_logger("gateway_control_pub")

    async def connect(self) -> None:
        """Connect to Redis."""
        self._client = redis.Redis(
            host=self.config.host,
            port=self.config.port,
            db=self.config.db,
            decode_responses=True,
        )
        await self._client.ping()
        self.logger.info("Connected to Redis for gateway control publishing")

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def publish(self, command: GatewayControlCommand) -> int:
        """Publish a gateway control command.

        Returns:
            Number of subscribers that received the message
        """
        if not self._client:
            raise RuntimeError("Not connected to Redis")

        message = json.dumps({
            "action": command.action,
            "symbols": command.symbols,
            "timestamp": command.timestamp.isoformat(),
        })

        result = await self._client.publish(self.channel, message)
        self.logger.info(
            "Published gateway control command",
            action=command.action,
            symbol_count=len(command.symbols),
            subscribers=result,
        )
        return result

    async def add_symbols(self, symbols: list[SymbolConfig]) -> int:
        """Publish add_symbols command."""
        return await self.publish(GatewayControlCommand(
            action="add_symbols",
            symbols=[{"symbol": s.symbol, "base_price": s.base_price} for s in symbols],
            timestamp=datetime.now(timezone.utc),
        ))

    async def remove_symbols(self, symbols: list[str]) -> int:
        """Publish remove_symbols command."""
        return await self.publish(GatewayControlCommand(
            action="remove_symbols",
            symbols=[{"symbol": s} for s in symbols],
            timestamp=datetime.now(timezone.utc),
        ))


class GatewayControlSubscriber:
    """Subscribes to gateway control commands via Redis pub/sub."""

    def __init__(self, config: RedisConfig, gateway_config: GatewayConfig):
        self.config = config
        self.channel = gateway_config.control_channel
        self._client: Optional[redis.Redis] = None
        self._pubsub: Optional[redis.client.PubSub] = None
        self.logger = get_logger("gateway_control_sub")

    async def connect(self) -> None:
        """Connect to Redis and subscribe to control channel."""
        self._client = redis.Redis(
            host=self.config.host,
            port=self.config.port,
            db=self.config.db,
            decode_responses=True,
        )
        await self._client.ping()

        self._pubsub = self._client.pubsub()
        await self._pubsub.subscribe(self.channel)
        self.logger.info("Subscribed to gateway control channel", channel=self.channel)

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._pubsub:
            await self._pubsub.unsubscribe(self.channel)
            await self._pubsub.aclose()
            self._pubsub = None

        if self._client:
            await self._client.aclose()
            self._client = None

    async def subscribe(self) -> AsyncIterator[GatewayControlCommand]:
        """Subscribe and yield gateway control commands."""
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
                command = GatewayControlCommand(
                    action=data["action"],
                    symbols=data["symbols"],
                    timestamp=datetime.fromisoformat(data["timestamp"]),
                )
                yield command

            except asyncio.CancelledError:
                break
            except json.JSONDecodeError as e:
                self.logger.warning("Invalid gateway control message", error=str(e))
            except Exception as e:
                self.logger.error("Error in gateway control subscriber", error=str(e))
                await asyncio.sleep(1.0)
