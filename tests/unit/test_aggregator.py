"""Unit tests for bar aggregation engine."""

from datetime import datetime, timezone

import pytest

from axtrade.aggregator.engine import (
    BarEngine,
    get_bar_start,
    parse_interval_seconds,
)
from axtrade.common import Tick


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

        completed = engine.flush()

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
