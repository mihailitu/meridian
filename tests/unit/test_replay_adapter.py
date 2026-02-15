"""Tests for the ReplayAdapter."""

import asyncio
import json
import tempfile
from datetime import datetime, timezone
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
