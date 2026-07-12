"""Tests for the discovery control channel (audit P1-3): the API process
publishes commands on axtrade:discovery:control instead of driving a live
DiscoveryService directly, since scanning now runs in the strategy-runner
process. Mirrors tests/unit/test_gateway_control.py's publisher tests."""

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from axtrade.common import Config, DiscoveryConfig, GatewayConfig, RedisConfig, SymbolConfig
from axtrade.discovery.control import (
    DiscoveryControlCommand,
    DiscoveryControlPublisher,
)
from axtrade.discovery.runner import DiscoveryRunner


class TestDiscoveryControlCommand:
    """Tests for DiscoveryControlCommand construction."""

    def test_scan_command(self):
        cmd = DiscoveryControlCommand(
            command="scan",
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert cmd.command == "scan"
        assert cmd.symbols == []

    def test_add_symbols_command(self):
        cmd = DiscoveryControlCommand(
            command="add_symbols",
            symbols=[{"symbol": "TSLA", "price": 250.0}],
            timestamp=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert cmd.command == "add_symbols"
        assert cmd.symbols[0]["symbol"] == "TSLA"


class TestDiscoveryControlPublisher:
    """Tests for DiscoveryControlPublisher (mirrors GatewayControlPublisher tests)."""

    @pytest.fixture
    def publisher(self):
        redis_config = RedisConfig(host="localhost", port=6379)
        discovery_config = DiscoveryConfig(control_channel="test:discovery:control")
        return DiscoveryControlPublisher(redis_config, discovery_config)

    async def test_scan_serialization(self, publisher):
        mock_client = AsyncMock()
        mock_client.publish = AsyncMock(return_value=1)
        publisher._client = mock_client

        result = await publisher.scan()
        assert result == 1

        call_args = mock_client.publish.call_args
        channel = call_args[0][0]
        message = json.loads(call_args[0][1])

        assert channel == "test:discovery:control"
        assert message["command"] == "scan"
        assert message["symbols"] == []

    async def test_add_symbols_serialization(self, publisher):
        mock_client = AsyncMock()
        mock_client.publish = AsyncMock(return_value=1)
        publisher._client = mock_client

        result = await publisher.add_symbols(
            [{"symbol": "TSLA", "price": 250.0, "notes": "earnings"}]
        )
        assert result == 1

        message = json.loads(mock_client.publish.call_args[0][1])
        assert message["command"] == "add_symbols"
        assert message["symbols"][0]["symbol"] == "TSLA"
        assert message["symbols"][0]["price"] == 250.0

    async def test_remove_symbols_serialization(self, publisher):
        mock_client = AsyncMock()
        mock_client.publish = AsyncMock(return_value=1)
        publisher._client = mock_client

        result = await publisher.remove_symbols()
        assert result == 1

        message = json.loads(mock_client.publish.call_args[0][1])
        assert message["command"] == "remove_symbols"
        assert message["symbols"] == []

    async def test_publish_not_connected_raises(self, publisher):
        with pytest.raises(RuntimeError, match="Not connected"):
            await publisher.scan()


def make_config(**discovery_overrides) -> Config:
    discovery_overrides.setdefault("enabled", True)
    return Config(
        gateway=GatewayConfig(symbols=[SymbolConfig(symbol="AAPL", base_price=185.0)]),
        discovery=DiscoveryConfig(**discovery_overrides),
    )


class TestDiscoveryRunnerControlCommandHandling:
    """Tests for DiscoveryRunner._handle_control_command: the runner-side
    handler that reacts to commands published by the API process."""

    @staticmethod
    def _mock_service() -> MagicMock:
        svc = MagicMock()
        svc.persist_discovered = AsyncMock()
        return svc

    def _runner(self, discovery_service=None) -> DiscoveryRunner:
        svc = discovery_service or self._mock_service()
        return DiscoveryRunner(
            config=make_config(),
            discovery_service=svc,
            symbol_provider=MagicMock(),
        )

    async def test_scan_command_triggers_scan(self):
        runner = self._runner()
        runner._do_scan = AsyncMock()

        await runner._handle_control_command(DiscoveryControlCommand(command="scan"))

        runner._do_scan.assert_called_once()

    async def test_scan_command_error_is_caught(self):
        runner = self._runner()
        runner._do_scan = AsyncMock(side_effect=RuntimeError("boom"))

        # Should not raise
        await runner._handle_control_command(DiscoveryControlCommand(command="scan"))

    async def test_add_symbols_command_calls_add_manual_symbol(self):
        svc = self._mock_service()
        runner = self._runner(discovery_service=svc)

        await runner._handle_control_command(
            DiscoveryControlCommand(
                command="add_symbols",
                symbols=[{"symbol": "TSLA", "price": 250.0, "notes": "earnings"}],
            )
        )

        svc.add_manual_symbol.assert_called_once_with(
            symbol="TSLA", price=250.0, notes="earnings"
        )
        # The API reads the DB, so the cache change must be persisted now,
        # not at the next periodic scan.
        svc.persist_discovered.assert_awaited_once()

    async def test_add_symbols_command_skips_entries_without_symbol(self):
        svc = self._mock_service()
        runner = self._runner(discovery_service=svc)

        await runner._handle_control_command(
            DiscoveryControlCommand(command="add_symbols", symbols=[{"price": 1.0}])
        )

        svc.add_manual_symbol.assert_not_called()
        svc.persist_discovered.assert_not_awaited()

    async def test_remove_symbols_command_clears_discovered(self):
        svc = self._mock_service()
        runner = self._runner(discovery_service=svc)

        await runner._handle_control_command(DiscoveryControlCommand(command="remove_symbols"))

        svc.clear_discovered.assert_called_once()
        svc.persist_discovered.assert_awaited_once()

    async def test_unknown_command_logged_and_ignored(self):
        svc = self._mock_service()
        runner = self._runner(discovery_service=svc)

        # Should not raise
        await runner._handle_control_command(DiscoveryControlCommand(command="bogus"))

        svc.add_manual_symbol.assert_not_called()
        svc.clear_discovered.assert_not_called()


class TestDiscoveryRunnerControlLoopLifecycle:
    """Tests that start()/stop() wire up the control subscriber correctly."""

    async def test_disabled_discovery_skips_control_subscriber(self):
        runner = DiscoveryRunner(
            config=make_config(enabled=False),
            discovery_service=MagicMock(),
            symbol_provider=MagicMock(),
        )

        await runner.start()

        assert runner._control_subscriber is None
        assert runner._control_task is None

    async def test_start_connects_control_subscriber_and_scans(self, monkeypatch):
        runner = DiscoveryRunner(
            config=make_config(scan_interval_seconds=1000),
            discovery_service=MagicMock(),
            symbol_provider=MagicMock(),
        )

        mock_subscriber = AsyncMock()

        async def empty_subscribe():
            return
            yield  # pragma: no cover - makes this an async generator

        mock_subscriber.subscribe = MagicMock(return_value=empty_subscribe())

        monkeypatch.setattr(
            "axtrade.discovery.runner.DiscoveryControlSubscriber",
            lambda *a, **kw: mock_subscriber,
        )

        runner._do_scan = AsyncMock()

        # Run start() briefly then stop it -- start() blocks on the scan
        # loop's sleep(interval), so give it one iteration and cancel.
        import asyncio

        task = asyncio.create_task(runner.start())
        await asyncio.sleep(0.05)
        await runner.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        mock_subscriber.connect.assert_called_once()
        mock_subscriber.disconnect.assert_called_once()
        runner._do_scan.assert_called()
