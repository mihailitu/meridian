"""Unit tests for HistoricalDataLoader."""

import json
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from axtrade.backtest import HistoricalDataLoader
from axtrade.common import Bar


@pytest.fixture
def temp_data_dir():
    """Create a temporary directory for test data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_df():
    """Create a sample dataframe with OHLCV data."""
    timestamps = pd.date_range(
        start="2024-01-15 09:30:00",
        periods=100,
        freq="1min",
        tz="UTC",
    )
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": [185.0 + i * 0.01 for i in range(100)],
        "high": [186.0 + i * 0.01 for i in range(100)],
        "low": [184.0 + i * 0.01 for i in range(100)],
        "close": [185.5 + i * 0.01 for i in range(100)],
        "volume": [1000 + i * 10 for i in range(100)],
        "sma_20": [None] * 19 + [185.0 + i * 0.005 for i in range(81)],
        "rsi_14": [None] * 15 + [50.0 + i * 0.1 for i in range(85)],
    })


@pytest.fixture
def data_dir_with_file(temp_data_dir, sample_df):
    """Create a temporary directory with a parquet file and manifest."""
    filename = "AAPL_1m_2024-01-15_2024-01-15.parquet"
    filepath = temp_data_dir / filename

    # Remove timezone for parquet (will be added back on load)
    df = sample_df.copy()
    df["timestamp"] = df["timestamp"].dt.tz_localize(None)

    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, filepath)

    manifest = {
        "files": [
            {
                "filename": filename,
                "symbol": "AAPL",
                "interval": "1m",
                "start_date": "2024-01-15",
                "end_date": "2024-01-15",
                "bar_count": 100,
                "collected_at": "2024-01-16T10:00:00Z",
                "has_indicators": True,
            }
        ]
    }

    with open(temp_data_dir / "manifest.json", "w") as f:
        json.dump(manifest, f)

    return temp_data_dir


class TestHistoricalDataLoader:
    """Tests for HistoricalDataLoader."""

    def test_list_available_empty(self, temp_data_dir):
        """Test listing available data with no manifest."""
        loader = HistoricalDataLoader(str(temp_data_dir))
        available = loader.list_available()
        assert available == []

    def test_list_available_from_manifest(self, data_dir_with_file):
        """Test listing available data from manifest."""
        loader = HistoricalDataLoader(str(data_dir_with_file))
        available = loader.list_available()

        assert len(available) == 1
        assert available[0]["symbol"] == "AAPL"
        assert available[0]["interval"] == "1m"
        assert available[0]["bar_count"] == 100

    def test_find_file_success(self, data_dir_with_file):
        """Test finding a file that exists."""
        loader = HistoricalDataLoader(str(data_dir_with_file))
        file_info = loader.find_file(
            symbol="AAPL",
            interval="1m",
            start=date(2024, 1, 15),
            end=date(2024, 1, 15),
        )

        assert file_info is not None
        assert file_info["symbol"] == "AAPL"

    def test_find_file_not_found_symbol(self, data_dir_with_file):
        """Test finding a file with wrong symbol."""
        loader = HistoricalDataLoader(str(data_dir_with_file))
        file_info = loader.find_file(
            symbol="MSFT",
            interval="1m",
            start=date(2024, 1, 15),
            end=date(2024, 1, 15),
        )

        assert file_info is None

    def test_find_file_not_found_interval(self, data_dir_with_file):
        """Test finding a file with wrong interval."""
        loader = HistoricalDataLoader(str(data_dir_with_file))
        file_info = loader.find_file(
            symbol="AAPL",
            interval="5m",
            start=date(2024, 1, 15),
            end=date(2024, 1, 15),
        )

        assert file_info is None

    def test_find_file_date_range_outside(self, data_dir_with_file):
        """Test finding a file when date range is outside available data."""
        loader = HistoricalDataLoader(str(data_dir_with_file))
        file_info = loader.find_file(
            symbol="AAPL",
            interval="1m",
            start=date(2024, 1, 10),
            end=date(2024, 1, 20),
        )

        assert file_info is None

    def test_load_bars_from_parquet(self, data_dir_with_file):
        """Test loading bars from parquet file."""
        loader = HistoricalDataLoader(str(data_dir_with_file))
        bars = loader.load_bars(
            symbol="AAPL",
            interval="1m",
            start=date(2024, 1, 15),
            end=date(2024, 1, 15),
        )

        assert len(bars) == 100
        assert isinstance(bars[0]["bar"], Bar)
        assert bars[0]["bar"].symbol == "AAPL"
        assert bars[0]["bar"].open == 185.0

    def test_load_bars_date_range_filter(self, data_dir_with_file):
        """Test loading bars filters by date range."""
        loader = HistoricalDataLoader(str(data_dir_with_file))

        # Request a subset of the data
        bars = loader.load_bars(
            symbol="AAPL",
            interval="1m",
            start=date(2024, 1, 15),
            end=date(2024, 1, 15),
        )

        # All 100 bars should be returned since they're all on 2024-01-15
        assert len(bars) == 100

        # Check first bar timestamp
        first_bar = bars[0]["bar"]
        assert first_bar.timestamp.date() == date(2024, 1, 15)

    def test_load_bars_with_indicators(self, data_dir_with_file):
        """Test that indicators are loaded from parquet."""
        loader = HistoricalDataLoader(str(data_dir_with_file))
        bars = loader.load_bars(
            symbol="AAPL",
            interval="1m",
            start=date(2024, 1, 15),
            end=date(2024, 1, 15),
        )

        # First 19 bars should have None for SMA-20
        assert bars[0]["sma_20"] is None

        # Bar at index 20 should have SMA-20
        assert bars[20]["sma_20"] is not None

        # First 15 bars should have None for RSI-14
        assert bars[0]["rsi_14"] is None

        # Bar at index 16 should have RSI-14
        assert bars[16]["rsi_14"] is not None

    def test_load_bars_missing_file_raises_error(self, temp_data_dir):
        """Test that loading from non-existent file raises error."""
        # Create manifest with a file that doesn't exist
        manifest = {
            "files": [
                {
                    "filename": "MISSING_1m_2024-01-15_2024-01-15.parquet",
                    "symbol": "MISSING",
                    "interval": "1m",
                    "start_date": "2024-01-15",
                    "end_date": "2024-01-15",
                    "bar_count": 100,
                    "collected_at": "2024-01-16T10:00:00Z",
                    "has_indicators": True,
                }
            ]
        }

        with open(temp_data_dir / "manifest.json", "w") as f:
            json.dump(manifest, f)

        loader = HistoricalDataLoader(str(temp_data_dir))

        with pytest.raises(FileNotFoundError):
            loader.load_bars(
                symbol="MISSING",
                interval="1m",
                start=date(2024, 1, 15),
                end=date(2024, 1, 15),
            )

    def test_load_bars_no_matching_file_raises_error(self, temp_data_dir):
        """Test that loading with no matching file raises error."""
        loader = HistoricalDataLoader(str(temp_data_dir))

        with pytest.raises(FileNotFoundError) as exc_info:
            loader.load_bars(
                symbol="AAPL",
                interval="1m",
                start=date(2024, 1, 15),
                end=date(2024, 1, 15),
            )

        assert "No data file found" in str(exc_info.value)

    def test_empty_manifest(self, temp_data_dir):
        """Test behavior with empty manifest."""
        manifest = {"files": []}

        with open(temp_data_dir / "manifest.json", "w") as f:
            json.dump(manifest, f)

        loader = HistoricalDataLoader(str(temp_data_dir))

        available = loader.list_available()
        assert available == []

        file_info = loader.find_file(
            symbol="AAPL",
            interval="1m",
            start=date(2024, 1, 15),
            end=date(2024, 1, 15),
        )
        assert file_info is None
