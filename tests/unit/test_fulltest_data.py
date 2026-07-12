"""Tests for fulltest historical data download (data.py)."""

import asyncio
import json
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from axtrade.fulltest.data import _chunk_ranges, download_historical_alpaca


# -- _chunk_ranges --


def test_chunk_ranges_non_overlapping():
    ranges = _chunk_ranges(date(2024, 1, 1), date(2024, 1, 31), chunk_days=7)
    for i in range(1, len(ranges)):
        prev_end = ranges[i - 1][1]
        cur_start = ranges[i][0]
        # Next chunk starts the day after the previous chunk's end.
        assert cur_start.date() == prev_end.date() + pd.Timedelta(days=1)


def test_chunk_ranges_full_coverage():
    start, end = date(2024, 1, 1), date(2024, 1, 31)
    ranges = _chunk_ranges(start, end, chunk_days=7)
    assert ranges[0][0].date() == start
    assert ranges[-1][1].date() == end
    # No gaps: cumulative day count matches the span.
    total_days = sum((r[1].date() - r[0].date()).days + 1 for r in ranges)
    assert total_days == (end - start).days + 1


def test_chunk_ranges_last_chunk_ends_on_end_date():
    ranges = _chunk_ranges(date(2024, 1, 1), date(2024, 1, 20), chunk_days=7)
    assert ranges[-1][1].date() == date(2024, 1, 20)


def test_chunk_ranges_single_chunk():
    ranges = _chunk_ranges(date(2024, 1, 1), date(2024, 1, 3), chunk_days=7)
    assert len(ranges) == 1
    assert ranges[0][0].date() == date(2024, 1, 1)
    assert ranges[0][1].date() == date(2024, 1, 3)


def test_chunk_ranges_respects_chunk_days():
    ranges = _chunk_ranges(date(2024, 1, 1), date(2024, 3, 1), chunk_days=3)
    for start_dt, end_dt in ranges[:-1]:
        assert (end_dt.date() - start_dt.date()).days == 2  # 3-day span inclusive

    # UTC time-of-day boundaries
    assert ranges[0][0].time() == datetime.min.time()
    assert ranges[0][1].hour == 23
    assert ranges[0][0].tzinfo == timezone.utc


# -- helpers for download tests --


def _make_bar(ts, o=100.0, h=101.0, l=99.0, c=100.5, v=1000):
    return SimpleNamespace(timestamp=ts, open=o, high=h, low=l, close=c, volume=v)


def _bar_set(symbol, bars):
    return SimpleNamespace(data={symbol: bars})


@pytest.fixture(autouse=True)
def _alpaca_env(monkeypatch):
    monkeypatch.setenv("ALPACA_API_KEY", "test-key")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test-secret")


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch):
    """Avoid real 2s retry sleeps / 0.25s rate-limit pauses in tests."""
    async def _noop(*args, **kwargs):
        return None
    monkeypatch.setattr(asyncio, "sleep", _noop)


def _patch_client(mock_client_cls, get_stock_bars):
    instance = MagicMock()
    instance.get_stock_bars.side_effect = get_stock_bars
    mock_client_cls.return_value = instance
    return instance


# -- adjustment --


async def test_split_adjustment_requested(tmp_path):
    ts = pd.Timestamp("2024-01-01 09:30:00", tz="UTC")
    bars = [_make_bar(ts)]

    with patch("alpaca.data.historical.StockHistoricalDataClient") as mock_client_cls, \
         patch("alpaca.data.requests.StockBarsRequest") as mock_request_cls:
        mock_request_cls.side_effect = lambda **kwargs: SimpleNamespace(**kwargs)
        _patch_client(mock_client_cls, lambda req: _bar_set("AAPL", bars))

        await download_historical_alpaca(
            symbols=["AAPL"],
            start=date(2024, 1, 1),
            end=date(2024, 1, 3),
            data_dir=str(tmp_path),
        )

        from alpaca.data.enums import Adjustment

        assert mock_request_cls.call_count >= 1
        for _, kwargs in mock_request_cls.call_args_list:
            assert kwargs["adjustment"] == Adjustment.SPLIT


# -- dedup --


async def test_duplicate_timestamps_deduped(tmp_path):
    ts = pd.Timestamp("2024-01-01 09:30:00", tz="UTC")
    ts2 = pd.Timestamp("2024-01-01 09:31:00", tz="UTC")
    # Simulate a duplicate bar (e.g. boundary overlap) within the returned data.
    bars = [_make_bar(ts), _make_bar(ts), _make_bar(ts2)]

    with patch("alpaca.data.historical.StockHistoricalDataClient") as mock_client_cls, \
         patch("alpaca.data.requests.StockBarsRequest") as mock_request_cls:
        mock_request_cls.side_effect = lambda **kwargs: SimpleNamespace(**kwargs)
        _patch_client(mock_client_cls, lambda req: _bar_set("AAPL", bars))

        result = await download_historical_alpaca(
            symbols=["AAPL"],
            start=date(2024, 1, 1),
            end=date(2024, 1, 3),
            data_dir=str(tmp_path),
        )

    filename = result["AAPL"]
    df = pq.read_table(tmp_path / filename).to_pandas()
    assert len(df) == 2
    assert df["timestamp"].is_unique


# -- failed chunk --


def _raise_boom(req):
    raise RuntimeError("boom")


async def test_failed_chunk_skips_symbol_no_manifest_entry(tmp_path):
    with patch("alpaca.data.historical.StockHistoricalDataClient") as mock_client_cls, \
         patch("alpaca.data.requests.StockBarsRequest") as mock_request_cls:
        mock_request_cls.side_effect = lambda **kwargs: SimpleNamespace(**kwargs)
        _patch_client(mock_client_cls, _raise_boom)

        result = await download_historical_alpaca(
            symbols=["AAPL"],
            start=date(2024, 1, 1),
            end=date(2024, 1, 3),
            data_dir=str(tmp_path),
        )

    assert "AAPL" not in result
    manifest_path = tmp_path / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        assert not any(f["symbol"] == "AAPL" for f in manifest.get("files", []))
    assert not any(tmp_path.glob("AAPL_*.parquet"))


# -- --force --


def _write_covering_manifest(data_dir, symbol, start, end):
    df = pd.DataFrame({
        "timestamp": [pd.Timestamp("2024-01-01 09:30:00")],
        "open": [100.0], "high": [101.0], "low": [99.0], "close": [100.5],
        "volume": [1000], "sma_20": [None], "rsi_14": [None],
    })
    filename = f"{symbol}_1m_{start}_{end}.parquet"
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, data_dir / filename)

    manifest = {
        "files": [{
            "filename": filename,
            "symbol": symbol,
            "interval": "1m",
            "start_date": str(start),
            "end_date": str(end),
            "bar_count": 1,
        }]
    }
    (data_dir / "manifest.json").write_text(json.dumps(manifest))


async def test_force_false_skips_already_covered(tmp_path):
    start, end = date(2024, 1, 1), date(2024, 1, 3)
    _write_covering_manifest(tmp_path, "AAPL", start, end)

    with patch("alpaca.data.historical.StockHistoricalDataClient") as mock_client_cls, \
         patch("alpaca.data.requests.StockBarsRequest") as mock_request_cls:
        mock_request_cls.side_effect = lambda **kwargs: SimpleNamespace(**kwargs)
        instance = _patch_client(mock_client_cls, lambda req: _bar_set("AAPL", [_make_bar(pd.Timestamp("2024-01-01 09:30:00", tz="UTC"))]))

        await download_historical_alpaca(
            symbols=["AAPL"],
            start=start,
            end=end,
            data_dir=str(tmp_path),
            force=False,
        )

        instance.get_stock_bars.assert_not_called()


async def test_force_true_redownloads_already_covered(tmp_path):
    start, end = date(2024, 1, 1), date(2024, 1, 3)
    _write_covering_manifest(tmp_path, "AAPL", start, end)

    with patch("alpaca.data.historical.StockHistoricalDataClient") as mock_client_cls, \
         patch("alpaca.data.requests.StockBarsRequest") as mock_request_cls:
        mock_request_cls.side_effect = lambda **kwargs: SimpleNamespace(**kwargs)
        instance = _patch_client(mock_client_cls, lambda req: _bar_set("AAPL", [_make_bar(pd.Timestamp("2024-01-01 09:30:00", tz="UTC"))]))

        await download_historical_alpaca(
            symbols=["AAPL"],
            start=start,
            end=end,
            data_dir=str(tmp_path),
            force=True,
        )

        instance.get_stock_bars.assert_called()
