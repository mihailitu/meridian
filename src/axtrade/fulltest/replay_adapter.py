"""Historical data replay adapter for full system backtest."""

import asyncio
import heapq
import json
import sys
from collections.abc import AsyncIterator
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import pyarrow.parquet as pq

from axtrade.common import SymbolConfig, Tick, get_logger
from axtrade.gateway.base import DataAdapter

logger = get_logger("fulltest.replay")


def _iter_file_bars(symbol: str, path: Path):
    """Yield (timestamp, symbol, open, high, low, close, volume) tuples from a parquet file.

    Reads the file into an Arrow table, converts columns to Python lists
    in batches via table.slice(), and yields lightweight tuples.
    The Arrow table is deleted after iteration to allow GC.
    """
    table = pq.read_table(path)
    n_rows = table.num_rows

    # Process in batches of 10000 rows to limit peak memory from .to_pylist()
    batch_size = 10000
    for offset in range(0, n_rows, batch_size):
        batch = table.slice(offset, min(batch_size, n_rows - offset))
        ts_col = batch.column("timestamp").to_pylist()
        open_col = batch.column("open").to_pylist()
        high_col = batch.column("high").to_pylist()
        low_col = batch.column("low").to_pylist()
        close_col = batch.column("close").to_pylist()
        vol_col = batch.column("volume").to_pylist()

        for i in range(len(ts_col)):
            ts = ts_col[i]
            # Ensure UTC
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            yield (ts, symbol, float(open_col[i]), float(high_col[i]),
                   float(low_col[i]), float(close_col[i]), int(vol_col[i]))

    del table


class ReplayAdapter(DataAdapter):
    """DataAdapter that replays historical parquet data as synthetic ticks.

    Converts each OHLCV bar into a sequence of ticks using price path
    interpolation:
      - Bullish bar (close >= open): O -> L -> H -> C
      - Bearish bar (close < open): O -> H -> L -> C

    Uses a heap-based streaming merge across parquet files to avoid loading
    all data into memory at once.
    """

    def __init__(
        self,
        data_dir: str,
        ticks_per_bar: int = 4,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ):
        self._data_dir = Path(data_dir)
        self._ticks_per_bar = max(ticks_per_bar, 4)
        self._start_date = start_date
        self._end_date = end_date
        self._manifest: Optional[dict] = None
        self._file_entries: list[tuple[str, Path]] = []
        self._symbols: list[str] = []
        self._connected = False
        self.completion_event = asyncio.Event()
        self.estimated_bars = 0
        self.total_bars = 0
        self.total_ticks = 0

    async def connect(self) -> None:
        """Load manifest and prepare data."""
        manifest_path = self._data_dir / "manifest.json"
        if manifest_path.exists():
            with open(manifest_path) as f:
                self._manifest = json.load(f)
        else:
            self._manifest = {"files": []}
        self._connected = True
        logger.info("Replay adapter connected", data_dir=str(self._data_dir))

    async def disconnect(self) -> None:
        """Disconnect the adapter."""
        self._connected = False
        self._file_entries = []

    async def subscribe(self, symbols: list[SymbolConfig]) -> None:
        """Record which parquet files to read for the requested symbols.

        No data is loaded at this stage -- files are streamed lazily in
        stream_ticks() via heap-based merge.
        """
        self._symbols = [s.symbol for s in symbols]
        self._file_entries = []
        self.estimated_bars = 0

        for file_info in self._manifest.get("files", []):
            symbol = file_info["symbol"]
            if symbol not in self._symbols:
                continue

            file_path = self._data_dir / file_info["filename"]
            if not file_path.exists():
                logger.warning("Missing parquet file", path=str(file_path))
                continue

            self._file_entries.append((symbol, file_path))
            self.estimated_bars += file_info.get("bar_count", 0)

        logger.info(
            "Prepared files for replay",
            symbols=len(self._symbols),
            files=len(self._file_entries),
            estimated_bars=self.estimated_bars,
        )

    def _make_ticks(self, symbol: str, ts: datetime,
                    o: float, h: float, l: float, c: float,
                    vol: int) -> list[Tick]:
        """Convert a single OHLCV bar to synthetic ticks.

        Uses price path interpolation:
          Bullish (close >= open): O -> L -> H -> C
          Bearish (close < open):  O -> H -> L -> C
        """
        is_bullish = c >= o

        if is_bullish:
            path = [o, l, h, c]
        else:
            path = [o, h, l, c]

        # If ticks_per_bar > 4, interpolate between path points
        if self._ticks_per_bar <= 4:
            prices = path
        else:
            prices = []
            segments = len(path) - 1
            points_per_segment = self._ticks_per_bar // segments
            remainder = self._ticks_per_bar % segments

            for i in range(segments):
                n = points_per_segment + (1 if i < remainder else 0)
                start_p = path[i]
                end_p = path[i + 1]
                for j in range(n):
                    t = j / max(n, 1)
                    prices.append(start_p + (end_p - start_p) * t)

            # Ensure we end at the close
            if len(prices) >= self._ticks_per_bar:
                prices = prices[:self._ticks_per_bar]
                prices[-1] = c
            else:
                prices.append(c)

        # Distribute volume across ticks
        vol_per_tick = max(vol // len(prices), 1)

        ticks = []
        for price in prices:
            tick = Tick(
                symbol=symbol,
                price=round(price, 4),
                timestamp=ts,
                volume=vol_per_tick,
            )
            ticks.append(tick)

        return ticks

    async def stream_ticks(self) -> AsyncIterator[Tick]:
        """Stream synthetic ticks from historical data.

        Uses heapq.merge() across per-file iterators for chronological
        ordering without loading all data into memory.
        Yields ticks without delay. Periodically yields control to the
        event loop for fairness.
        """
        # Guard against repeated calls after replay is complete (the
        # gateway's stream loop retries until stopped by the orchestrator).
        # Park with an async sleep so we don't starve the event loop;
        # the gateway will cancel us when it shuts down.
        if self.completion_event.is_set():
            await asyncio.sleep(86400)
            return

        iterators = [
            _iter_file_bars(symbol, path)
            for symbol, path in self._file_entries
        ]

        tick_count = 0
        bar_count = 0

        # Pre-compute date boundaries as UTC datetimes for fast comparison
        start_dt = (
            datetime.combine(self._start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            if self._start_date else None
        )
        end_dt = (
            datetime.combine(self._end_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            if self._end_date else None
        )

        for bar_tuple in heapq.merge(*iterators):
            ts, symbol, o, h, l, c, vol = bar_tuple

            # Filter bars outside the requested date range
            if start_dt and ts < start_dt:
                continue
            if end_dt and ts >= end_dt:
                continue

            ticks = self._make_ticks(symbol, ts, o, h, l, c, vol)
            bar_count += 1

            if bar_count % 1000 == 0 and self.estimated_bars > 0:
                pct = min(bar_count * 100 // self.estimated_bars, 99)
                date_str = ts.strftime("%Y-%m-%d %H:%M")
                print(f"\rProgress: {pct:3d}% ({bar_count} bars) | {symbol} {date_str}  ", end="", file=sys.stderr, flush=True)

            for tick in ticks:
                yield tick
                tick_count += 1

                # Yield to event loop every 100 ticks
                if tick_count % 100 == 0:
                    await asyncio.sleep(0)

        if self.estimated_bars > 0:
            print(f"\rProgress: 100% ({bar_count} bars) -- replay complete.                    ", file=sys.stderr)

        self.total_bars = bar_count
        self.total_ticks = tick_count
        logger.info(
            "Replay complete",
            total_bars=self.total_bars,
            total_ticks=tick_count,
        )
        self.completion_event.set()

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def name(self) -> str:
        return "replay"
