#!/usr/bin/env python3
"""Historical data collector using yfinance.

Downloads OHLCV data and saves to parquet files with indicators calculated.

Usage:
    python scripts/collect_historical.py AAPL MSFT --start 2024-01-01 --end 2024-06-30 --interval 1m
"""

import argparse
import json
import sys
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import yfinance as yf

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from axtrade.indicators import calculate_rsi, calculate_sma


VALID_INTERVALS = ["1m", "5m", "15m", "1h", "1d"]


def calculate_indicators(df):
    """Calculate SMA-20 and RSI-14 for the dataframe.

    Args:
        df: DataFrame with OHLCV data

    Returns:
        DataFrame with sma_20 and rsi_14 columns added
    """
    closes = df["close"].tolist()
    sma_period = 20
    rsi_period = 14

    sma_values = []
    rsi_values = []

    buffer = deque(maxlen=max(sma_period, rsi_period + 1) + 10)

    for close in closes:
        buffer.append(close)

        sma = calculate_sma(list(buffer), sma_period)
        rsi = calculate_rsi(list(buffer), rsi_period)

        sma_values.append(round(sma, 6) if sma is not None else None)
        rsi_values.append(rsi)

    df["sma_20"] = sma_values
    df["rsi_14"] = rsi_values

    return df


def download_data(symbol: str, start: str, end: str, interval: str):
    """Download historical data from yfinance.

    Args:
        symbol: Stock symbol
        start: Start date YYYY-MM-DD
        end: End date YYYY-MM-DD
        interval: Bar interval

    Returns:
        DataFrame with OHLCV data or None if download failed
    """
    print(f"Downloading {symbol} data ({interval}) from {start} to {end}...")

    ticker = yf.Ticker(symbol)

    try:
        df = ticker.history(start=start, end=end, interval=interval)
    except Exception as e:
        print(f"  Error downloading {symbol}: {e}")
        return None

    if df.empty:
        print(f"  No data returned for {symbol}")
        return None

    # Rename columns to lowercase
    df.columns = [c.lower() for c in df.columns]

    # Keep only OHLCV columns
    df = df[["open", "high", "low", "close", "volume"]].copy()

    # Reset index to get timestamp as column
    df = df.reset_index()
    df = df.rename(columns={"Date": "timestamp", "Datetime": "timestamp"})

    # Ensure timestamp column exists
    if "timestamp" not in df.columns and "index" in df.columns:
        df = df.rename(columns={"index": "timestamp"})

    # Convert timezone-aware timestamps to UTC then remove timezone
    if df["timestamp"].dt.tz is not None:
        df["timestamp"] = df["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None)

    print(f"  Downloaded {len(df)} bars")
    return df


def save_to_parquet(df, output_path: Path):
    """Save dataframe to parquet file.

    Args:
        df: DataFrame to save
        output_path: Path to output file
    """
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, output_path, compression="snappy")
    print(f"  Saved to {output_path}")


def update_manifest(manifest_path: Path, file_info: dict):
    """Update manifest.json with new file entry.

    Args:
        manifest_path: Path to manifest.json
        file_info: File metadata to add
    """
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = json.load(f)
    else:
        manifest = {"files": []}

    # Remove existing entry for same file if present
    manifest["files"] = [
        f for f in manifest["files"]
        if f["filename"] != file_info["filename"]
    ]

    manifest["files"].append(file_info)

    # Sort by filename
    manifest["files"].sort(key=lambda x: x["filename"])

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"  Updated {manifest_path}")


def collect_symbol(
    symbol: str,
    start: str,
    end: str,
    interval: str,
    output_dir: Path,
) -> bool:
    """Collect data for a single symbol.

    Args:
        symbol: Stock symbol
        start: Start date
        end: End date
        interval: Bar interval
        output_dir: Output directory

    Returns:
        True if successful, False otherwise
    """
    df = download_data(symbol, start, end, interval)
    if df is None:
        return False

    print(f"  Calculating indicators...")
    df = calculate_indicators(df)

    # Build filename
    filename = f"{symbol}_{interval}_{start}_{end}.parquet"
    output_path = output_dir / filename

    save_to_parquet(df, output_path)

    # Build file info for manifest
    file_info = {
        "filename": filename,
        "symbol": symbol,
        "interval": interval,
        "start_date": start,
        "end_date": end,
        "bar_count": len(df),
        "collected_at": datetime.now(timezone.utc).isoformat(),
        "has_indicators": True,
    }

    update_manifest(output_dir / "manifest.json", file_info)

    return True


def main():
    parser = argparse.ArgumentParser(
        description="Collect historical market data using yfinance"
    )
    parser.add_argument(
        "symbols",
        nargs="+",
        help="List of symbols to collect (e.g., AAPL MSFT)",
    )
    parser.add_argument(
        "--start",
        required=True,
        help="Start date YYYY-MM-DD",
    )
    parser.add_argument(
        "--end",
        required=True,
        help="End date YYYY-MM-DD",
    )
    parser.add_argument(
        "--interval",
        default="1m",
        choices=VALID_INTERVALS,
        help="Bar interval (default: 1m)",
    )
    parser.add_argument(
        "--output-dir",
        default="data/historical",
        help="Output directory (default: data/historical)",
    )

    args = parser.parse_args()

    # Validate interval
    if args.interval not in VALID_INTERVALS:
        print(f"Error: Invalid interval '{args.interval}'")
        print(f"Valid intervals: {', '.join(VALID_INTERVALS)}")
        sys.exit(1)

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Collecting data for {len(args.symbols)} symbol(s)")
    print(f"Output directory: {output_dir.absolute()}")
    print()

    success_count = 0
    for symbol in args.symbols:
        symbol = symbol.upper()
        if collect_symbol(symbol, args.start, args.end, args.interval, output_dir):
            success_count += 1
        print()

    print(f"Completed: {success_count}/{len(args.symbols)} symbols collected successfully")

    if success_count < len(args.symbols):
        sys.exit(1)


if __name__ == "__main__":
    main()
