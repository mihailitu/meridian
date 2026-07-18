"""Unit tests for bar aggregation engine."""

import socket
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from axtrade.aggregator.engine import (
    BarEngine,
    get_bar_start,
    parse_interval_seconds,
)
from axtrade.aggregator.service import AggregatorService
from axtrade.common import Bar, Config, Tick


class TestParseIntervalSeconds:
    """Tests for interval parsing."""

    def test_seconds(self) -> None:
        assert parse_interval_seconds("30s") == 30
        assert parse_interval_seconds("1s") == 1

    def test_minutes(self) -> None:
        assert parse_interval_seconds("1m") == 60
        assert parse_interval_seconds("5m") == 300
        assert parse_interval_seconds("15m") == 900

    def test_hours(self) -> None:
        assert parse_interval_seconds("1h") == 3600
        assert parse_interval_seconds("4h") == 14400

    def test_days(self) -> None:
        assert parse_interval_seconds("1d") == 86400

    def test_invalid_unit(self) -> None:
        with pytest.raises(ValueError, match="Unknown interval unit"):
            parse_interval_seconds("1x")


class TestGetBarStart:
    """Tests for bar start time alignment."""

    def test_1m_alignment(self) -> None:
        # 09:31:45 should align to 09:31:00
        ts = datetime(2024, 1, 15, 9, 31, 45, tzinfo=timezone.utc)
        bar_start = get_bar_start(ts, 60)
        assert bar_start == datetime(2024, 1, 15, 9, 31, 0, tzinfo=timezone.utc)

    def test_5m_alignment(self) -> None:
        # 09:33:00 should align to 09:30:00
        ts = datetime(2024, 1, 15, 9, 33, 0, tzinfo=timezone.utc)
        bar_start = get_bar_start(ts, 300)
        assert bar_start == datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc)

    def test_exact_boundary(self) -> None:
        # 09:30:00 should stay 09:30:00
        ts = datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc)
        bar_start = get_bar_start(ts, 60)
        assert bar_start == ts


class TestBarEngine:
    """Tests for bar aggregation engine."""

    def test_single_tick_creates_open_bar(self) -> None:
        engine = BarEngine(["1m"])
        tick = Tick(
            symbol="AAPL",
            price=185.0,
            timestamp=datetime(2024, 1, 15, 9, 30, 15, tzinfo=timezone.utc),
            volume=100,
        )

        completed = engine.process_tick(tick)
        assert completed == []

        open_bar = engine.get_open_bar("AAPL", "1m")
        assert open_bar is not None
        assert open_bar.open == 185.0
        assert open_bar.high == 185.0
        assert open_bar.low == 185.0
        assert open_bar.close == 185.0
        assert open_bar.volume == 100

    def test_ticks_within_same_bar(self) -> None:
        engine = BarEngine(["1m"])
        base_time = datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc)

        ticks = [
            Tick("AAPL", 185.0, base_time, volume=100),
            Tick("AAPL", 185.5, base_time.replace(second=15), volume=50),
            Tick("AAPL", 184.8, base_time.replace(second=30), volume=75),
            Tick("AAPL", 185.2, base_time.replace(second=45), volume=25),
        ]

        for tick in ticks:
            completed = engine.process_tick(tick)
            assert completed == []

        open_bar = engine.get_open_bar("AAPL", "1m")
        assert open_bar is not None
        assert open_bar.open == 185.0
        assert open_bar.high == 185.5
        assert open_bar.low == 184.8
        assert open_bar.close == 185.2
        assert open_bar.volume == 250

    def test_bar_completion_on_new_period(self) -> None:
        engine = BarEngine(["1m"])

        # First bar period (09:30:xx)
        tick1 = Tick(
            "AAPL", 185.0,
            datetime(2024, 1, 15, 9, 30, 30, tzinfo=timezone.utc),
            volume=100,
        )
        engine.process_tick(tick1)

        # New bar period (09:31:xx) - should complete previous bar
        tick2 = Tick(
            "AAPL", 186.0,
            datetime(2024, 1, 15, 9, 31, 15, tzinfo=timezone.utc),
            volume=50,
        )
        completed = engine.process_tick(tick2)

        assert len(completed) == 1
        bar, interval = completed[0]
        assert interval == "1m"
        assert bar.symbol == "AAPL"
        assert bar.open == 185.0
        assert bar.close == 185.0
        assert bar.volume == 100
        assert bar.timestamp == datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc)

    def test_multiple_intervals(self) -> None:
        engine = BarEngine(["1m", "5m"])

        tick = Tick(
            "AAPL", 185.0,
            datetime(2024, 1, 15, 9, 30, 15, tzinfo=timezone.utc),
            volume=100,
        )
        engine.process_tick(tick)

        # Both intervals should have open bars
        assert engine.get_open_bar("AAPL", "1m") is not None
        assert engine.get_open_bar("AAPL", "5m") is not None

    def test_multiple_symbols(self) -> None:
        engine = BarEngine(["1m"])
        base_time = datetime(2024, 1, 15, 9, 30, 15, tzinfo=timezone.utc)

        engine.process_tick(Tick("AAPL", 185.0, base_time, volume=100))
        engine.process_tick(Tick("MSFT", 420.0, base_time, volume=200))

        aapl_bar = engine.get_open_bar("AAPL", "1m")
        msft_bar = engine.get_open_bar("MSFT", "1m")

        assert aapl_bar is not None
        assert aapl_bar.open == 185.0

        assert msft_bar is not None
        assert msft_bar.open == 420.0

    def test_flush_returns_all_open_bars(self) -> None:
        engine = BarEngine(["1m", "5m"])
        base_time = datetime(2024, 1, 15, 9, 30, 15, tzinfo=timezone.utc)

        engine.process_tick(Tick("AAPL", 185.0, base_time, volume=100))
        engine.process_tick(Tick("MSFT", 420.0, base_time, volume=200))

        completed, partial = engine.flush()

        # With no as_of, everything is treated as elapsed (backward-compatible).
        assert partial == []

        # Should have 4 bars: AAPL 1m, AAPL 5m, MSFT 1m, MSFT 5m
        assert len(completed) == 4

        symbols = {bar.symbol for bar, _ in completed}
        intervals = {interval for _, interval in completed}

        assert symbols == {"AAPL", "MSFT"}
        assert intervals == {"1m", "5m"}

    def test_flush_clears_open_bars(self) -> None:
        engine = BarEngine(["1m"])
        tick = Tick(
            "AAPL", 185.0,
            datetime(2024, 1, 15, 9, 30, 15, tzinfo=timezone.utc),
            volume=100,
        )

        engine.process_tick(tick)
        assert engine.get_open_bar("AAPL", "1m") is not None

        engine.flush()
        assert engine.get_open_bar("AAPL", "1m") is None

    def test_flush_as_of_past_all_windows_is_all_elapsed(self) -> None:
        engine = BarEngine(["1m"])
        engine.process_tick(
            Tick(
                "AAPL", 185.0,
                datetime(2024, 1, 15, 9, 30, 15, tzinfo=timezone.utc),
                volume=100,
            )
        )

        as_of = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        completed, partial = engine.flush(as_of=as_of)

        assert len(completed) == 1
        assert partial == []

    def test_flush_as_of_mid_window_is_partial(self) -> None:
        engine = BarEngine(["1m"])
        engine.process_tick(
            Tick(
                "AAPL", 185.0,
                datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
                volume=100,
            )
        )

        # Bar started at 09:30:00; as_of 09:30:30 is still within the
        # 1m window, so no future tick's absence can be assumed yet.
        as_of = datetime(2024, 1, 15, 9, 30, 30, tzinfo=timezone.utc)
        completed, partial = engine.flush(as_of=as_of)

        assert completed == []
        assert len(partial) == 1
        assert partial[0][0].symbol == "AAPL"

    def test_flush_as_of_exact_boundary_is_elapsed(self) -> None:
        engine = BarEngine(["1m"])
        engine.process_tick(
            Tick(
                "AAPL", 185.0,
                datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
                volume=100,
            )
        )

        # as_of == bar_start + interval exactly should count as elapsed (<=).
        as_of = datetime(2024, 1, 15, 9, 31, 0, tzinfo=timezone.utc)
        completed, partial = engine.flush(as_of=as_of)

        assert len(completed) == 1
        assert partial == []

    def test_flush_as_of_mixed_intervals(self) -> None:
        engine = BarEngine(["1m", "5m"])
        engine.process_tick(
            Tick(
                "AAPL", 185.0,
                datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
                volume=100,
            )
        )

        # 09:32 is past the 1m window (09:30-09:31) but still within
        # the 5m window (09:30-09:35).
        as_of = datetime(2024, 1, 15, 9, 32, 0, tzinfo=timezone.utc)
        completed, partial = engine.flush(as_of=as_of)

        assert len(completed) == 1
        assert completed[0][1] == "1m"
        assert len(partial) == 1
        assert partial[0][1] == "5m"

    def test_flush_clears_open_bars_even_with_partials(self) -> None:
        engine = BarEngine(["1m"])
        engine.process_tick(
            Tick(
                "AAPL", 185.0,
                datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
                volume=100,
            )
        )

        as_of = datetime(2024, 1, 15, 9, 30, 30, tzinfo=timezone.utc)
        completed, partial = engine.flush(as_of=as_of)
        assert completed == []
        assert len(partial) == 1

        # Open bars are cleared regardless of elapsed/partial classification.
        assert engine.get_open_bar("AAPL", "1m") is None

        # A subsequent tick starts a fresh bar rather than resuming the
        # dropped partial.
        engine.process_tick(
            Tick(
                "AAPL", 190.0,
                datetime(2024, 1, 15, 9, 31, 0, tzinfo=timezone.utc),
                volume=10,
            )
        )
        new_open = engine.get_open_bar("AAPL", "1m")
        assert new_open is not None
        assert new_open.open == 190.0
        assert new_open.volume == 10

    def test_tick_without_volume(self) -> None:
        engine = BarEngine(["1m"])
        tick = Tick(
            "AAPL", 185.0,
            datetime(2024, 1, 15, 9, 30, 15, tzinfo=timezone.utc),
            volume=None,
        )

        engine.process_tick(tick)
        open_bar = engine.get_open_bar("AAPL", "1m")

        assert open_bar is not None
        assert open_bar.volume == 0

    def test_5m_bar_completion(self) -> None:
        engine = BarEngine(["5m"])

        # Tick at 09:33:00 (belongs to 09:30 bar)
        tick1 = Tick(
            "AAPL", 185.0,
            datetime(2024, 1, 15, 9, 33, 0, tzinfo=timezone.utc),
            volume=100,
        )
        engine.process_tick(tick1)

        # Tick at 09:35:00 (new 5m bar) - should complete previous
        tick2 = Tick(
            "AAPL", 186.0,
            datetime(2024, 1, 15, 9, 35, 0, tzinfo=timezone.utc),
            volume=50,
        )
        completed = engine.process_tick(tick2)

        assert len(completed) == 1
        bar, interval = completed[0]
        assert interval == "5m"
        assert bar.timestamp == datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc)


class TestAggregatorServiceConsumerName:
    """Tests for AggregatorService consumer naming."""

    def test_consumer_name_is_stable_by_hostname(self) -> None:
        """Consumer name must be stable across restarts (audit P2-7) so
        Redis PEL recovery can find this consumer's own pending entries."""
        service = AggregatorService(Config())
        assert service._consumer_name == f"aggregator-{socket.gethostname()}"


class TestAggregatorServiceStop:
    """Tests for AggregatorService.stop() partial-bar handling (audit P2-8)."""

    @pytest.mark.asyncio
    async def test_stop_publishes_elapsed_and_drops_partial(self) -> None:
        service = AggregatorService(Config())

        elapsed_bar = Bar(
            symbol="AAPL",
            open=185.0,
            high=185.5,
            low=184.8,
            close=185.2,
            volume=250,
            timestamp=datetime(2024, 1, 15, 9, 29, 0, tzinfo=timezone.utc),
        )
        partial_bar = Bar(
            symbol="MSFT",
            open=420.0,
            high=421.0,
            low=419.0,
            close=420.5,
            volume=100,
            timestamp=datetime(2024, 1, 15, 9, 30, 0, tzinfo=timezone.utc),
        )

        service._engine = MagicMock()
        service._engine.flush.return_value = (
            [(elapsed_bar, "1m")],
            [(partial_bar, "1m")],
        )
        service._consumer = AsyncMock()
        service._publisher = AsyncMock()
        service._db_pool = AsyncMock()
        service._process_completed_bar = AsyncMock()
        service.logger = MagicMock()

        await service.stop()

        service._process_completed_bar.assert_awaited_once_with(elapsed_bar, "1m")
        service.logger.warning.assert_called_once()
        warning_kwargs = service.logger.warning.call_args.kwargs
        assert warning_kwargs["count"] == 1
        assert warning_kwargs["bars"] == [("MSFT", "1m", partial_bar.timestamp.isoformat())]

        service._consumer.disconnect.assert_awaited_once()
        service._publisher.disconnect.assert_awaited_once()
        service._db_pool.disconnect.assert_awaited_once()
