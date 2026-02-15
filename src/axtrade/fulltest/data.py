"""Historical data download via Alpaca API."""

import json
from collections import deque
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from axtrade.common import get_logger
from axtrade.indicators import calculate_rsi, calculate_sma

logger = get_logger("fulltest.data")


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


def save_to_parquet(df, output_path: Path):
    """Save dataframe to parquet file."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, output_path, compression="snappy")
    logger.info("Saved parquet", path=str(output_path), rows=len(df))


def update_manifest(manifest_path: Path, file_info: dict):
    """Update manifest.json with new file entry."""
    if manifest_path.exists():
        with open(manifest_path) as f:
            manifest = json.load(f)
    else:
        manifest = {"files": []}

    manifest["files"] = [
        f for f in manifest["files"]
        if f["filename"] != file_info["filename"]
    ]
    manifest["files"].append(file_info)
    manifest["files"].sort(key=lambda x: x["filename"])

    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)


def _check_manifest_for_symbol(
    data_dir: Path,
    symbol: str,
    interval: str,
    start: date,
    end: date,
) -> Optional[str]:
    """Check if data already exists in manifest.

    Returns:
        Filename if found, None otherwise
    """
    manifest_path = data_dir / "manifest.json"
    if not manifest_path.exists():
        return None

    with open(manifest_path) as f:
        manifest = json.load(f)

    for entry in manifest.get("files", []):
        if entry["symbol"] != symbol or entry["interval"] != interval:
            continue
        file_start = date.fromisoformat(entry["start_date"])
        file_end = date.fromisoformat(entry["end_date"])
        if file_start <= start and file_end >= end:
            file_path = data_dir / entry["filename"]
            if file_path.exists():
                return entry["filename"]

    return None


async def download_historical_alpaca(
    symbols: list[str],
    start: date,
    end: date,
    interval: str = "1m",
    data_dir: str = "data/historical",
) -> dict[str, str]:
    """Download historical data via Alpaca API.

    Downloads bars in weekly chunks to handle API limits.

    Args:
        symbols: List of stock symbols
        start: Start date
        end: End date
        interval: Bar interval
        data_dir: Directory to save parquet files

    Returns:
        Dict mapping symbol -> parquet filename
    """
    import asyncio

    import pandas as pd
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockBarsRequest
    from alpaca.data.timeframe import TimeFrame

    # Load Alpaca credentials from env
    import os
    api_key = os.environ.get("ALPACA_API_KEY", "")
    secret_key = os.environ.get("ALPACA_SECRET_KEY", "")

    if not api_key or not secret_key:
        raise ValueError(
            "ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables required"
        )

    output_dir = Path(data_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Map interval string to Alpaca TimeFrame
    timeframe_map = {
        "1m": TimeFrame.Minute,
        "5m": TimeFrame(5, "Min"),
        "15m": TimeFrame(15, "Min"),
        "1h": TimeFrame.Hour,
        "1d": TimeFrame.Day,
    }
    timeframe = timeframe_map.get(interval)
    if not timeframe:
        raise ValueError(f"Unsupported interval: {interval}")

    client = StockHistoricalDataClient(api_key, secret_key)
    result_files = {}

    for symbol in symbols:
        # Check if data already exists
        existing = _check_manifest_for_symbol(output_dir, symbol, interval, start, end)
        if existing:
            logger.info("Data already exists", symbol=symbol, file=existing)
            result_files[symbol] = existing
            continue

        logger.info(
            "Downloading",
            symbol=symbol,
            start=str(start),
            end=str(end),
            interval=interval,
        )

        # Download in weekly chunks
        all_bars = []
        chunk_start = start
        chunk_size = timedelta(days=7)

        while chunk_start < end:
            chunk_end = min(chunk_start + chunk_size, end)
            start_dt = datetime.combine(chunk_start, datetime.min.time()).replace(
                tzinfo=timezone.utc
            )
            end_dt = datetime.combine(chunk_end, datetime.max.time()).replace(
                tzinfo=timezone.utc
            )

            try:
                request = StockBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=timeframe,
                    start=start_dt,
                    end=end_dt,
                )
                bars = client.get_stock_bars(request)

                if bars and symbol in bars.data:
                    for bar in bars.data[symbol]:
                        all_bars.append({
                            "timestamp": bar.timestamp,
                            "open": float(bar.open),
                            "high": float(bar.high),
                            "low": float(bar.low),
                            "close": float(bar.close),
                            "volume": int(bar.volume),
                        })

                logger.debug(
                    "Chunk downloaded",
                    symbol=symbol,
                    chunk=f"{chunk_start} to {chunk_end}",
                    bars=len(all_bars),
                )
            except Exception as e:
                logger.warning(
                    "Chunk download failed",
                    symbol=symbol,
                    chunk=f"{chunk_start} to {chunk_end}",
                    error=str(e),
                )

            chunk_start = chunk_end
            # Brief pause for rate limiting
            await asyncio.sleep(0.25)

        if not all_bars:
            logger.warning("No data downloaded", symbol=symbol)
            continue

        df = pd.DataFrame(all_bars)
        df = df.sort_values("timestamp").reset_index(drop=True)

        # Remove timezone info for parquet compatibility
        if df["timestamp"].dt.tz is not None:
            df["timestamp"] = df["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None)

        logger.info("Calculating indicators", symbol=symbol, bars=len(df))
        df = calculate_indicators(df)

        filename = f"{symbol}_{interval}_{start}_{end}.parquet"
        output_path = output_dir / filename
        save_to_parquet(df, output_path)

        file_info = {
            "filename": filename,
            "symbol": symbol,
            "interval": interval,
            "start_date": str(start),
            "end_date": str(end),
            "bar_count": len(df),
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "has_indicators": True,
            "source": "alpaca",
        }
        update_manifest(output_dir / "manifest.json", file_info)
        result_files[symbol] = filename

        logger.info(
            "Symbol complete",
            symbol=symbol,
            bars=len(df),
            file=filename,
        )

    return result_files
