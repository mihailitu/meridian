"""Tests for the ReplayAdapter."""

import asyncio
import json
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from axtrade.common import SymbolConfig
from axtrade.fulltest.replay_adapter import ReplayAdapter


def _create_test_data(data_dir: Path, symbol: str, bars: list[dict]) -> None:
    """Create parquet file and manifest for testing."""
    df = pd.DataFrame(bars)
    filename = f"{symbol}_1m_test.parquet"
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, data_dir / filename, compression="snappy")

    manifest = {
        "files": [
            {
                "filename": filename,
                "symbol": symbol,
                "interval": "1m",
                "start_date": "2025-01-01",
                "end_date": "2025-12-31",
                "bar_count": len(bars),
            }
        ]
    }
    with open(data_dir / "manifest.json", "w") as f:
        json.dump(manifest, f)


@pytest.fixture
def sample_bars():
    """Create sample bar data."""
    return [
        {
            "timestamp": pd.Timestamp("2025-06-01 09:30:00", tz="UTC"),
            "open": 100.0,
            "high": 102.0,
            "low": 99.0,
            "close": 101.5,
            "volume": 1000,
        },
        {
            "timestamp": pd.Timestamp("2025-06-01 09:31:00", tz="UTC"),
            "open": 101.5,
            "high": 103.0,
            "low": 100.5,
            "close": 100.0,
            "volume": 800,
        },
        {
            "timestamp": pd.Timestamp("2025-06-01 09:32:00", tz="UTC"),
            "open": 100.0,
            "high": 101.0,
            "low": 99.5,
            "close": 101.0,
            "volume": 1200,
        },
    ]


@pytest.fixture
def data_dir(tmp_path, sample_bars):
    """Create a temp directory with test data."""
    _create_test_data(tmp_path, "AAPL", sample_bars)
    return tmp_path


async def test_connect_loads_manifest(data_dir):
    adapter = ReplayAdapter(str(data_dir))
    await adapter.connect()

    assert adapter.connected
    assert adapter._manifest is not None
    assert len(adapter._manifest["files"]) == 1


async def test_subscribe_loads_bars(data_dir):
    adapter = ReplayAdapter(str(data_dir))
    await adapter.connect()
    await adapter.subscribe([SymbolConfig(symbol="AAPL", base_price=100.0)])

    assert len(adapter._file_entries) == 1
    assert adapter.estimated_bars == 3


async def test_subscribe_filters_symbols(data_dir):
    adapter = ReplayAdapter(str(data_dir))
    await adapter.connect()
    # Subscribe to a symbol not in our data
    await adapter.subscribe([SymbolConfig(symbol="MSFT", base_price=200.0)])

    assert len(adapter._file_entries) == 0
    assert adapter.estimated_bars == 0


async def test_stream_ticks_produces_correct_count(data_dir):
    adapter = ReplayAdapter(str(data_dir), ticks_per_bar=4)
    await adapter.connect()
    await adapter.subscribe([SymbolConfig(symbol="AAPL", base_price=100.0)])

    ticks = []
    async for tick in adapter.stream_ticks():
        ticks.append(tick)

    # 3 bars * 4 ticks per bar = 12 ticks
    assert len(ticks) == 12
    assert adapter.completion_event.is_set()


async def test_stream_ticks_bullish_bar_path(data_dir):
    """Bullish bar (close >= open) follows O -> L -> H -> C path."""
    adapter = ReplayAdapter(str(data_dir), ticks_per_bar=4)
    await adapter.connect()
    await adapter.subscribe([SymbolConfig(symbol="AAPL", base_price=100.0)])

    ticks = []
    async for tick in adapter.stream_ticks():
        ticks.append(tick)

    # First bar: O=100, H=102, L=99, C=101.5 (bullish: close > open)
    # Path should be: O(100) -> L(99) -> H(102) -> C(101.5)
    first_bar_ticks = ticks[:4]
    prices = [t.price for t in first_bar_ticks]
    assert prices[0] == 100.0  # Open
    assert prices[1] == 99.0   # Low
    assert prices[2] == 102.0  # High
    assert prices[3] == 101.5  # Close


async def test_stream_ticks_bearish_bar_path(data_dir):
    """Bearish bar (close < open) follows O -> H -> L -> C path."""
    adapter = ReplayAdapter(str(data_dir), ticks_per_bar=4)
    await adapter.connect()
    await adapter.subscribe([SymbolConfig(symbol="AAPL", base_price=100.0)])

    ticks = []
    async for tick in adapter.stream_ticks():
        ticks.append(tick)

    # Second bar: O=101.5, H=103, L=100.5, C=100.0 (bearish: close < open)
    # Path should be: O(101.5) -> H(103) -> L(100.5) -> C(100.0)
    second_bar_ticks = ticks[4:8]
    prices = [t.price for t in second_bar_ticks]
    assert prices[0] == 101.5  # Open
    assert prices[1] == 103.0  # High
    assert prices[2] == 100.5  # Low
    assert prices[3] == 100.0  # Close


async def test_ticks_are_chronologically_ordered(data_dir):
    adapter = ReplayAdapter(str(data_dir), ticks_per_bar=4)
    await adapter.connect()
    await adapter.subscribe([SymbolConfig(symbol="AAPL", base_price=100.0)])

    timestamps = []
    async for tick in adapter.stream_ticks():
        timestamps.append(tick.timestamp)

    # Each bar's ticks share the same timestamp, but bars are ordered
    # Check that timestamps are non-decreasing
    for i in range(1, len(timestamps)):
        assert timestamps[i] >= timestamps[i - 1]


async def test_completion_event_set_after_all_ticks(data_dir):
    adapter = ReplayAdapter(str(data_dir), ticks_per_bar=4)
    await adapter.connect()
    await adapter.subscribe([SymbolConfig(symbol="AAPL", base_price=100.0)])

    assert not adapter.completion_event.is_set()

    async for _ in adapter.stream_ticks():
        pass

    assert adapter.completion_event.is_set()
    assert adapter.total_ticks == 12


async def test_multiple_symbols_interleaved(tmp_path):
    """When multiple symbols are loaded, ticks are interleaved by time."""
    ts1 = pd.Timestamp("2025-06-01 09:30:00", tz="UTC")
    ts2 = pd.Timestamp("2025-06-01 09:31:00", tz="UTC")

    bars_aapl = [
        {"timestamp": ts1, "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 500},
        {"timestamp": ts2, "open": 101.0, "high": 103.0, "low": 100.0, "close": 102.0, "volume": 600},
    ]
    bars_msft = [
        {"timestamp": ts1, "open": 200.0, "high": 204.0, "low": 198.0, "close": 203.0, "volume": 400},
        {"timestamp": ts2, "open": 203.0, "high": 205.0, "low": 201.0, "close": 204.0, "volume": 300},
    ]

    # Create files
    for symbol, bars in [("AAPL", bars_aapl), ("MSFT", bars_msft)]:
        df = pd.DataFrame(bars)
        filename = f"{symbol}_1m_test.parquet"
        table = pa.Table.from_pandas(df, preserve_index=False)
        pq.write_table(table, tmp_path / filename)

    manifest = {
        "files": [
            {"filename": "AAPL_1m_test.parquet", "symbol": "AAPL", "interval": "1m",
             "start_date": "2025-01-01", "end_date": "2025-12-31", "bar_count": 2},
            {"filename": "MSFT_1m_test.parquet", "symbol": "MSFT", "interval": "1m",
             "start_date": "2025-01-01", "end_date": "2025-12-31", "bar_count": 2},
        ]
    }
    with open(tmp_path / "manifest.json", "w") as f:
        json.dump(manifest, f)

    adapter = ReplayAdapter(str(tmp_path), ticks_per_bar=4)
    await adapter.connect()
    await adapter.subscribe([
        SymbolConfig(symbol="AAPL", base_price=100.0),
        SymbolConfig(symbol="MSFT", base_price=200.0),
    ])

    assert len(adapter._file_entries) == 2
    assert adapter.estimated_bars == 4  # 2 per symbol

    ticks = []
    async for tick in adapter.stream_ticks():
        ticks.append(tick)

    # 4 bars * 4 ticks = 16 ticks total
    assert len(ticks) == 16
    assert adapter.total_bars == 4

    # Both symbols present
    symbols = set(t.symbol for t in ticks)
    assert symbols == {"AAPL", "MSFT"}


async def test_disconnect_clears_state(data_dir):
    adapter = ReplayAdapter(str(data_dir))
    await adapter.connect()
    await adapter.subscribe([SymbolConfig(symbol="AAPL", base_price=100.0)])

    assert adapter.connected
    assert len(adapter._file_entries) == 1

    await adapter.disconnect()
    assert not adapter.connected
    assert len(adapter._file_entries) == 0


async def test_adapter_name(data_dir):
    adapter = ReplayAdapter(str(data_dir))
    assert adapter.name == "replay"


def _write_manifest(data_dir: Path, entries: list[dict]) -> None:
    with open(data_dir / "manifest.json", "w") as f:
        json.dump({"files": entries}, f)


def _write_parquet(data_dir: Path, filename: str, bars: list[dict]) -> None:
    df = pd.DataFrame(bars)
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, data_dir / filename, compression="snappy")


@pytest.fixture
def two_window_manifest(tmp_path):
    """Two files per symbol: 2024-08->2025-08 (IS) and 2025-08->2026-02 (OOS)."""
    bars_is = [
        {"timestamp": pd.Timestamp("2025-01-01 09:30:00", tz="UTC"), "open": 100.0,
         "high": 101.0, "low": 99.0, "close": 100.5, "volume": 500},
    ]
    bars_oos = [
        {"timestamp": pd.Timestamp("2025-09-01 09:30:00", tz="UTC"), "open": 200.0,
         "high": 201.0, "low": 199.0, "close": 200.5, "volume": 500},
    ]
    for symbol in ("AAPL", "MSFT"):
        _write_parquet(tmp_path, f"{symbol}_1m_is.parquet", bars_is)
        _write_parquet(tmp_path, f"{symbol}_1m_oos.parquet", bars_oos)

    entries = []
    for symbol in ("AAPL", "MSFT"):
        entries.append({
            "filename": f"{symbol}_1m_is.parquet", "symbol": symbol, "interval": "1m",
            "start_date": "2024-08-01", "end_date": "2025-08-01", "bar_count": 1,
        })
        entries.append({
            "filename": f"{symbol}_1m_oos.parquet", "symbol": symbol, "interval": "1m",
            "start_date": "2025-08-01", "end_date": "2026-02-01", "bar_count": 1,
        })
    _write_manifest(tmp_path, entries)
    return tmp_path


async def test_subscribe_selects_only_overlapping_window(two_window_manifest):
    adapter = ReplayAdapter(
        str(two_window_manifest),
        start_date=date(2024, 8, 1), end_date=date(2025, 8, 1),
    )
    await adapter.connect()
    await adapter.subscribe([
        SymbolConfig(symbol="AAPL", base_price=100.0),
        SymbolConfig(symbol="MSFT", base_price=200.0),
    ])

    filenames = {path.name for _, path in adapter._file_entries}
    assert filenames == {"AAPL_1m_is.parquet", "MSFT_1m_is.parquet"}


async def test_subscribe_selects_both_files_when_window_spans_both(two_window_manifest):
    adapter = ReplayAdapter(
        str(two_window_manifest),
        start_date=date(2024, 8, 1), end_date=date(2026, 2, 1),
    )
    await adapter.connect()
    await adapter.subscribe([SymbolConfig(symbol="AAPL", base_price=100.0)])

    filenames = {path.name for _, path in adapter._file_entries}
    assert filenames == {"AAPL_1m_is.parquet", "AAPL_1m_oos.parquet"}


async def test_add_symbols_selects_only_overlapping_window(two_window_manifest):
    adapter = ReplayAdapter(
        str(two_window_manifest),
        start_date=date(2024, 8, 1), end_date=date(2025, 8, 1),
    )
    await adapter.connect()
    await adapter.add_symbols([SymbolConfig(symbol="AAPL", base_price=100.0)])

    pending = adapter._drain_pending()
    assert [p.name for _, p in pending] == ["AAPL_1m_is.parquet"]


async def test_add_symbols_no_overlap_logs_warning_and_skips(two_window_manifest, monkeypatch):
    # Window entirely before both files' coverage.
    adapter = ReplayAdapter(
        str(two_window_manifest),
        start_date=date(2020, 1, 1), end_date=date(2020, 6, 1),
    )
    await adapter.connect()

    # structlog isn't routed through stdlib logging (no setup_logging() call
    # in tests), so caplog can't see it -- assert on the logger call directly.
    from axtrade.fulltest import replay_adapter as replay_module
    warnings = []
    monkeypatch.setattr(
        replay_module.logger, "warning",
        lambda event, **kw: warnings.append((event, kw)),
    )

    await adapter.add_symbols([SymbolConfig(symbol="AAPL", base_price=100.0)])

    assert adapter._drain_pending() == []
    assert any("no data file covers run window" in event.lower() for event, _ in warnings)


async def test_stream_ticks_monotonic_guard_dedupes_overlap_day(tmp_path):
    """Two files for one symbol overlap on 2025-06-02; the guard should emit
    each (symbol, timestamp) bar exactly once."""
    ts_file1 = [
        pd.Timestamp("2025-06-01 09:30:00", tz="UTC"),
        pd.Timestamp("2025-06-02 09:30:00", tz="UTC"),  # overlap day
    ]
    ts_file2 = [
        pd.Timestamp("2025-06-02 09:30:00", tz="UTC"),  # overlap day (duplicate)
        pd.Timestamp("2025-06-03 09:30:00", tz="UTC"),
    ]

    def _mk(ts_list, base):
        return [
            {"timestamp": ts, "open": base, "high": base + 1, "low": base - 1,
             "close": base + 0.5, "volume": 100}
            for ts in ts_list
        ]

    _write_parquet(tmp_path, "AAPL_1m_a.parquet", _mk(ts_file1, 100.0))
    _write_parquet(tmp_path, "AAPL_1m_b.parquet", _mk(ts_file2, 200.0))

    _write_manifest(tmp_path, [
        {"filename": "AAPL_1m_a.parquet", "symbol": "AAPL", "interval": "1m",
         "start_date": "2025-06-01", "end_date": "2025-06-02", "bar_count": 2},
        {"filename": "AAPL_1m_b.parquet", "symbol": "AAPL", "interval": "1m",
         "start_date": "2025-06-02", "end_date": "2025-06-03", "bar_count": 2},
    ])

    adapter = ReplayAdapter(str(tmp_path), ticks_per_bar=4)
    await adapter.connect()
    await adapter.subscribe([SymbolConfig(symbol="AAPL", base_price=100.0)])
    assert len(adapter._file_entries) == 2

    ticks = []
    async for tick in adapter.stream_ticks():
        ticks.append(tick)

    seen = [(t.symbol, t.timestamp) for t in ticks]
    unique_bar_timestamps = {t.timestamp for t in ticks}
    # 3 distinct bar timestamps (06-01, 06-02, 06-03), each appears exactly once.
    assert len(unique_bar_timestamps) == 3
    assert adapter.total_bars == 3
    # No duplicate (symbol, timestamp) pairs among emitted ticks' bar groups.
    for ts in unique_bar_timestamps:
        count = sum(1 for s, t in seen if t == ts)
        assert count == 4  # ticks_per_bar, i.e. exactly one bar emitted for this ts


async def test_more_ticks_per_bar(data_dir):
    """With more ticks per bar, interpolation creates intermediate prices."""
    adapter = ReplayAdapter(str(data_dir), ticks_per_bar=8)
    await adapter.connect()
    await adapter.subscribe([SymbolConfig(symbol="AAPL", base_price=100.0)])

    ticks = []
    async for tick in adapter.stream_ticks():
        ticks.append(tick)

    # 3 bars * 8 ticks per bar = 24 ticks
    assert len(ticks) == 24

    # First bar ticks should start at open and end at close
    first_bar_ticks = ticks[:8]
    assert first_bar_ticks[0].price == 100.0   # Open
    assert first_bar_ticks[-1].price == 101.5  # Close
