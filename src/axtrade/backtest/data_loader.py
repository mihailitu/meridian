"""Historical data loader for file-based backtesting."""

import json
import math
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import pyarrow.parquet as pq

from axtrade.common import Bar


def _safe_float(value) -> Optional[float]:
    """Convert a value to float, returning None if NaN or None."""
    if value is None:
        return None
    try:
        f = float(value)
        if math.isnan(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


class HistoricalDataLoader:
    """Loads historical bar data from parquet files."""

    def __init__(self, data_dir: str = "data/historical"):
        """Initialize the data loader.

        Args:
            data_dir: Directory containing parquet files and manifest.json
        """
        self.data_dir = Path(data_dir)
        self._manifest: Optional[dict] = None

    @property
    def manifest(self) -> dict:
        """Load and cache the manifest file."""
        if self._manifest is None:
            manifest_path = self.data_dir / "manifest.json"
            if not manifest_path.exists():
                self._manifest = {"files": []}
            else:
                with open(manifest_path) as f:
                    self._manifest = json.load(f)
        return self._manifest

    def list_available(self) -> list[dict]:
        """List available data files from manifest.

        Returns:
            List of file metadata dictionaries
        """
        return self.manifest.get("files", [])

    def find_file(
        self,
        symbol: str,
        interval: str,
        start: date,
        end: date,
    ) -> Optional[dict]:
        """Find a file that covers the requested date range.

        Args:
            symbol: Stock symbol
            interval: Bar interval
            start: Start date
            end: End date

        Returns:
            File metadata if found, None otherwise
        """
        for file_info in self.list_available():
            if file_info["symbol"] != symbol:
                continue
            if file_info["interval"] != interval:
                continue

            file_start = date.fromisoformat(file_info["start_date"])
            file_end = date.fromisoformat(file_info["end_date"])

            # Check if file covers requested range
            if file_start <= start and file_end >= end:
                return file_info

        return None

    def load_bars(
        self,
        symbol: str,
        interval: str,
        start: date,
        end: date,
    ) -> list[dict]:
        """Load bars from parquet file matching criteria.

        Args:
            symbol: Stock symbol
            interval: Bar interval
            start: Start date
            end: End date

        Returns:
            List of bar dictionaries with 'bar', 'sma_20', 'rsi_14' keys

        Raises:
            FileNotFoundError: If no matching file found
        """
        file_info = self.find_file(symbol, interval, start, end)
        if file_info is None:
            raise FileNotFoundError(
                f"No data file found for {symbol} {interval} "
                f"covering {start} to {end}"
            )

        file_path = self.data_dir / file_info["filename"]
        if not file_path.exists():
            raise FileNotFoundError(f"Data file not found: {file_path}")

        # Read parquet file
        table = pq.read_table(file_path)
        df = table.to_pandas()

        # Convert timestamps if they are timezone-naive
        if df["timestamp"].dt.tz is None:
            df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
        else:
            df["timestamp"] = df["timestamp"].dt.tz_convert("UTC")

        # Filter by date range
        start_dt = datetime.combine(start, datetime.min.time()).replace(tzinfo=timezone.utc)
        end_dt = datetime.combine(end, datetime.max.time()).replace(tzinfo=timezone.utc)

        df = df[(df["timestamp"] >= start_dt) & (df["timestamp"] <= end_dt)]

        # Convert to list of bar dictionaries
        bars = []
        for _, row in df.iterrows():
            bar = Bar(
                symbol=symbol,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row["volume"]),
                timestamp=row["timestamp"].to_pydatetime(),
            )
            bar_data = {
                "bar": bar,
                "sma_20": _safe_float(row.get("sma_20")) if "sma_20" in row.index else None,
                "rsi_14": _safe_float(row.get("rsi_14")) if "rsi_14" in row.index else None,
            }
            bars.append(bar_data)

        return bars
