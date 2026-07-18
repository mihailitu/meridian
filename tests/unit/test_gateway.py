"""Tests for gateway module."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from axtrade.common import MockConfig, RedisPublisher, SymbolConfig, Tick
from axtrade.gateway import MockAdapter
from axtrade.gateway.control import GatewayControlSubscriber
from axtrade.gateway.service import PUBLISH_FAILURE_ESCALATION_THRESHOLD, GatewayService


class TestMockAdapter:
    """Tests for MockAdapter."""

    @pytest.fixture
    def adapter(self, mock_config):
        """Create a mock adapter for testing."""
        return MockAdapter(mock_config)

    @pytest.fixture
    def symbols(self):
        """Create test symbols."""
        return [
            SymbolConfig(symbol="TEST1", base_price=100.00),
            SymbolConfig(symbol="TEST2", base_price=200.00),
        ]

    async def test_connect(self, adapter):
        """Test adapter connection."""
        assert not adapter.connected
        await adapter.connect()
        assert adapter.connected

    async def test_disconnect(self, adapter):
        """Test adapter disconnection."""
        await adapter.connect()
        await adapter.disconnect()
        assert not adapter.connected

    async def test_subscribe(self, adapter, symbols):
        """Test symbol subscription."""
        await adapter.connect()
        await adapter.subscribe(symbols)

        assert adapter.get_price("TEST1") == 100.00
        assert adapter.get_price("TEST2") == 200.00

    async def test_stream_ticks(self, adapter, symbols):
        """Test tick streaming."""
        await adapter.connect()
        await adapter.subscribe(symbols)

        tick_count = 0
        async for tick in adapter.stream_ticks():
            assert isinstance(tick, Tick)
            assert tick.symbol in ["TEST1", "TEST2"]
            assert tick.price > 0
            assert tick.bid is not None
            assert tick.ask is not None
            tick_count += 1
            if tick_count >= 4:
                await adapter.disconnect()
                break

        assert tick_count >= 4

    def test_name(self, adapter):
        """Test adapter name."""
        assert adapter.name == "mock"

    async def test_seeded_ticks_are_deterministic(self, symbols):
        """Two adapters with the same seed must produce identical price
        sequences (MockConfig.seed drives a per-adapter random.Random)."""

        async def collect_prices(seed: int, count: int) -> list[float]:
            cfg = MockConfig(tick_interval_ms=1, volatility=0.001, seed=seed)
            adapter = MockAdapter(cfg)
            await adapter.connect()
            await adapter.subscribe(symbols)

            prices = []
            async for tick in adapter.stream_ticks():
                prices.append(tick.price)
                if len(prices) >= count:
                    await adapter.disconnect()
                    break
            return prices

        prices_a = await collect_prices(seed=42, count=10)
        prices_b = await collect_prices(seed=42, count=10)

        assert prices_a == prices_b

    async def test_unseeded_ticks_are_still_generated(self, symbols):
        """A None seed (the default) must not break tick generation."""
        cfg = MockConfig(tick_interval_ms=1, volatility=0.001, seed=None)
        adapter = MockAdapter(cfg)
        await adapter.connect()
        await adapter.subscribe(symbols)

        async for tick in adapter.stream_ticks():
            assert tick.price > 0
            await adapter.disconnect()
            break


class TestTick:
    """Tests for Tick dataclass."""

    def test_to_dict(self):
        """Test tick serialization."""
        from datetime import datetime

        tick = Tick(
            symbol="AAPL",
            price=185.50,
            timestamp=datetime(2024, 1, 15, 9, 30, 0),
            bid=185.49,
            ask=185.51,
            volume=1000,
        )

        data = tick.to_dict()

        assert data["symbol"] == "AAPL"
        assert data["price"] == "185.5"
        assert data["bid"] == "185.49"
        assert data["ask"] == "185.51"
        assert data["volume"] == "1000"
        assert "2024-01-15" in data["timestamp"]

    def test_to_dict_zero_values_are_not_blanked(self):
        """bid=0.0/ask=0.0/volume=0 are legitimate values and must not be
        serialized as empty string like an absent value would be."""
        from datetime import datetime

        tick = Tick(
            symbol="AAPL",
            price=185.50,
            timestamp=datetime(2024, 1, 15, 9, 30, 0),
            bid=0.0,
            ask=0.0,
            volume=0,
        )

        data = tick.to_dict()

        assert data["bid"] == "0.0"
        assert data["ask"] == "0.0"
        assert data["volume"] == "0"

    def test_tick_immutable(self):
        """Test that tick is immutable."""
        tick = Tick(symbol="AAPL", price=185.50)

        with pytest.raises(Exception):
            tick.price = 186.00


class TestGatewayServiceStart:
    """Tests for GatewayService.start() (audit P2-9: fail fast when Redis
    is unreachable at startup, instead of degrading to a permanent no-op)."""

    async def test_start_raises_when_redis_connect_fails(self, config):
        """A Redis connect failure at startup must propagate, not be
        swallowed into a `continuing_without_redis` no-op mode."""
        adapter = MockAdapter(config.gateway.mock)
        service = GatewayService(config, adapter=adapter)

        with patch.object(
            RedisPublisher, "connect", side_effect=ConnectionError("redis down")
        ):
            with pytest.raises(ConnectionError, match="redis down"):
                await service.start()

        # The old fallback nulled the publisher out; that path is gone now.
        assert service._publisher is not None

    async def test_start_starts_control_subscriber_unconditionally(self, config):
        """The control subscriber must start regardless of the (now
        fail-fast) publisher connection outcome - the old `if self._publisher:`
        guard only ever existed for the publisher-is-None case."""
        adapter = MockAdapter(config.gateway.mock)
        service = GatewayService(config, adapter=adapter)

        with (
            patch.object(RedisPublisher, "connect", new=AsyncMock()),
            patch.object(GatewayControlSubscriber, "connect", new=AsyncMock()),
            patch.object(GatewayService, "_control_loop", new=AsyncMock()),
            patch.object(GatewayService, "_stream_loop", new=AsyncMock()),
        ):
            await service.start()

        assert service._control_subscriber is not None
        assert service._control_task is not None


class TestGatewayServiceStreamLoopPublishFailures:
    """Tests for per-tick publish failure handling in _stream_loop (audit
    P2-9)."""

    def _make_service(self, config) -> GatewayService:
        adapter = MockAdapter(config.gateway.mock)
        service = GatewayService(config, adapter=adapter)
        # _stream_loop is being exercised directly (not via start()), so
        # populate the attributes start() would normally set up.
        service._adapter = adapter
        return service

    async def test_repeated_publish_failures_escalate_to_supervisor(self, config):
        """Consecutive publish failures reaching the escalation threshold
        must be re-raised so the stream supervisor's handle_error sees them;
        reset_errors must NOT be called along that path."""
        service = self._make_service(config)

        ticks = [
            Tick(symbol="AAPL", price=100.0 + i)
            for i in range(PUBLISH_FAILURE_ESCALATION_THRESHOLD + 1)
        ]

        async def fake_stream_ticks():
            for tick in ticks:
                yield tick

        service._adapter.stream_ticks = fake_stream_ticks

        fake_publisher = AsyncMock()
        fake_publisher.publish_tick = AsyncMock(side_effect=Exception("publish boom"))
        service._publisher = fake_publisher

        mock_supervisor = Mock()
        mock_supervisor.handle_error = AsyncMock(return_value=False)
        mock_supervisor.reset_errors = Mock()
        service._stream_supervisor = mock_supervisor

        service._running = True
        await service._stream_loop()

        mock_supervisor.handle_error.assert_awaited_once()
        mock_supervisor.reset_errors.assert_not_called()

    async def test_publish_failure_counter_resets_on_success(self, config):
        """A run of failures below the threshold followed by a success must
        reset the consecutive-failure counter and call reset_errors, without
        ever escalating to handle_error."""
        service = self._make_service(config)

        ticks = [Tick(symbol="AAPL", price=100.0 + i) for i in range(4)]

        async def fake_stream_ticks():
            for tick in ticks:
                yield tick
            # Stop the outer while-loop once all ticks are consumed so the
            # mocked loop terminates instead of restarting forever.
            service._running = False

        service._adapter.stream_ticks = fake_stream_ticks

        fake_publisher = AsyncMock()
        fake_publisher.publish_tick = AsyncMock(
            side_effect=[Exception("boom"), Exception("boom"), Exception("boom"), None]
        )
        service._publisher = fake_publisher

        mock_supervisor = Mock()
        mock_supervisor.handle_error = AsyncMock()
        mock_supervisor.reset_errors = Mock()
        service._stream_supervisor = mock_supervisor

        service._running = True
        await service._stream_loop()

        assert service._publish_failures == 0
        mock_supervisor.reset_errors.assert_called_once()
        mock_supervisor.handle_error.assert_not_called()
