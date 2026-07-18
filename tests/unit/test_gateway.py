"""Tests for gateway module."""

import asyncio
import time
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from axtrade.common import AlpacaConfig, MockConfig, RedisPublisher, SymbolConfig, Tick
from axtrade.gateway import MockAdapter
from axtrade.gateway.alpaca import _STREAM_DEAD, AlpacaAdapter
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


class TestAlpacaAdapterEmitTick:
    """Tests for the thread-safe tick handoff (audit P2-10). Handlers run on
    the stream's own event loop inside the executor thread, so ticks must be
    handed to the gateway loop via call_soon_threadsafe rather than a bare
    put_nowait, which isn't thread-safe and doesn't wake the getter."""

    def test_emit_tick_with_loop_uses_call_soon_threadsafe(self):
        adapter = AlpacaAdapter(AlpacaConfig())
        fake_loop = MagicMock()
        fake_loop.is_closed.return_value = False
        adapter._loop = fake_loop

        tick = Tick(symbol="AAPL", price=100.0)
        adapter._emit_tick(tick)

        fake_loop.call_soon_threadsafe.assert_called_once_with(adapter._enqueue, tick)
        assert adapter._tick_queue.empty()  # not enqueued directly

        # Invoking the scheduled callback (as the real loop would) puts the
        # tick on the queue.
        callback, *args = fake_loop.call_soon_threadsafe.call_args[0]
        callback(*args)
        assert adapter._tick_queue.get_nowait() is tick

    def test_emit_tick_without_loop_enqueues_directly(self):
        adapter = AlpacaAdapter(AlpacaConfig())
        adapter._loop = None

        tick = Tick(symbol="AAPL", price=100.0)
        adapter._emit_tick(tick)

        assert adapter._tick_queue.get_nowait() is tick

    async def test_handle_trade_routes_through_emit_tick(self):
        adapter = AlpacaAdapter(AlpacaConfig())
        adapter._emit_tick = Mock()

        fake_trade = Mock()
        fake_trade.symbol = "AAPL"
        fake_trade.price = 123.45
        fake_trade.timestamp = datetime(2024, 1, 15, 9, 30, 0, tzinfo=UTC)
        fake_trade.size = 10

        await adapter._handle_trade(fake_trade)

        adapter._emit_tick.assert_called_once()
        tick = adapter._emit_tick.call_args[0][0]
        assert tick.symbol == "AAPL"
        assert tick.price == 123.45
        assert tick.volume == 10
        assert tick.timestamp == fake_trade.timestamp


class TestAlpacaAdapterStreamDeath:
    """Tests for loud stream-death detection and rebuild-on-retry (audit
    P2-10). Without _on_stream_run_done, stream.run() raising or returning
    silently stops all tick flow with zero errors."""

    def test_on_stream_run_done_exception_enqueues_sentinel(self):
        adapter = AlpacaAdapter(AlpacaConfig())
        adapter._running = True
        fut = Mock()
        fut.cancelled.return_value = False
        fut.exception.return_value = RuntimeError("boom")

        adapter._on_stream_run_done(fut)

        assert adapter._stream_death_error == "boom"
        assert adapter._tick_queue.get_nowait() is _STREAM_DEAD

    def test_on_stream_run_done_not_running_is_ignored(self):
        adapter = AlpacaAdapter(AlpacaConfig())
        adapter._running = False
        fut = Mock()
        fut.cancelled.return_value = False
        fut.exception.return_value = None

        adapter._on_stream_run_done(fut)

        assert adapter._tick_queue.empty()

    def test_on_stream_run_done_cancelled_is_ignored(self):
        adapter = AlpacaAdapter(AlpacaConfig())
        adapter._running = True
        fut = Mock()
        fut.cancelled.return_value = True

        adapter._on_stream_run_done(fut)

        assert adapter._tick_queue.empty()

    async def test_stream_ticks_raises_on_stream_death(self):
        adapter = AlpacaAdapter(AlpacaConfig())
        fake_stream = MagicMock()
        fake_stream.run = Mock(return_value=None)  # returns immediately -> "died"
        adapter._stream = fake_stream
        adapter._connected = True

        async def consume():
            async for _ in adapter.stream_ticks():
                pass

        with pytest.raises(RuntimeError, match="alpaca stream died"):
            await asyncio.wait_for(consume(), timeout=5)

        assert adapter._stream_dead is True

    async def test_stream_ticks_rebuilds_stream_on_reentry_after_death(self):
        adapter = AlpacaAdapter(AlpacaConfig())
        adapter._stream = MagicMock()  # old, dead stream object
        adapter._stream_dead = True
        adapter._stream_death_error = "boom"
        adapter._symbols = [SymbolConfig(symbol="AAPL", base_price=100.0)]

        def fake_connect_side_effect():
            new_stream = MagicMock()
            new_stream.run = Mock(return_value=None)  # dies again immediately
            adapter._stream = new_stream
            adapter._connected = True

        adapter.disconnect = AsyncMock()
        adapter.connect = AsyncMock(side_effect=fake_connect_side_effect)
        adapter.subscribe = AsyncMock()

        async def consume():
            async for _ in adapter.stream_ticks():
                pass

        with pytest.raises(RuntimeError, match="alpaca stream died"):
            await asyncio.wait_for(consume(), timeout=5)

        adapter.connect.assert_awaited_once()
        adapter.subscribe.assert_awaited_once_with(list(adapter._symbols))
        # The rebuild cleared the flag before the second death set it again.
        assert adapter._stream_dead is True
        assert adapter._stream_death_error != "boom"


class TestGatewayServiceStalenessWatchdog:
    """Tests for the cross-adapter tick-staleness watchdog (audit P2-10)."""

    async def test_watchdog_warns_then_resumes(self, config):
        config.gateway.tick_staleness_seconds = 1
        service = GatewayService(config)
        service._running = True
        service._last_tick_monotonic = time.monotonic() - 10

        with patch("axtrade.gateway.service.logger") as mock_logger:
            task = asyncio.create_task(service._staleness_watchdog())
            try:
                await asyncio.sleep(0.4)
                assert mock_logger.warning.call_count == 1
                assert service._tick_stale_flagged is True

                service._last_tick_monotonic = time.monotonic()
                await asyncio.sleep(0.3)
                assert mock_logger.info.call_count == 1
                assert service._tick_stale_flagged is False
            finally:
                service._running = False
                try:
                    await asyncio.wait_for(task, timeout=2)
                except asyncio.TimeoutError:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass


class TestGatewayConfigTickStaleness:
    """Tests for GatewayConfig.tick_staleness_seconds defaults."""

    def test_default_is_300(self):
        from axtrade.common import GatewayConfig

        assert GatewayConfig().tick_staleness_seconds == 300
