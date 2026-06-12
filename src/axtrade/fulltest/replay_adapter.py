"""Historical data replay adapter for full system backtest."""

import asyncio
import heapq
import json
import sys
import threading
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
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


@dataclass(order=False)
class _HeapEntry:
    """Wrapper for heap items that compares by (timestamp, index) to avoid
    tuple comparison issues when timestamps are equal."""
    timestamp: datetime
    idx: int
    bar_tuple: tuple
    iterator: object = field(repr=False, compare=False)

    def __lt__(self, other: "_HeapEntry") -> bool:
        if self.timestamp != other.timestamp:
            return self.timestamp < other.timestamp
        return self.idx < other.idx


class ReplayAdapter(DataAdapter):
    """DataAdapter that replays historical parquet data as synthetic ticks.

    Converts each OHLCV bar into a sequence of ticks using price path
    interpolation:
      - Bullish bar (close >= open): O -> L -> H -> C
      - Bearish bar (close < open): O -> H -> L -> C

    Uses a heap-based streaming merge across parquet files to avoid loading
    all data into memory at once. Supports dynamic add_symbols() for
    discovery-driven symbol injection during replay.
    """

    def __init__(
        self,
        data_dir: str,
        ticks_per_bar: int = 4,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        throttle: Optional[Callable[[], Awaitable[None]]] = None,
    ):
        """
        Args:
            throttle: Optional async callback awaited periodically during
                streaming. Used by the orchestrator to pace the producer to
                the consumers: without it the whole window is pushed into
                Redis in seconds while the aggregator's sim clock is still
                on day one, so discovery-driven add_symbols() fires after
                the producer has already finished and fed symbols never
                replay a single bar.
        """
        self._data_dir = Path(data_dir)
        self._ticks_per_bar = max(ticks_per_bar, 4)
        self._start_date = start_date
        self._end_date = end_date
        self._throttle = throttle
        self._manifest: Optional[dict] = None
        self._file_entries: list[tuple[str, Path]] = []
        self._symbols: list[str] = []
        self._connected = False
        self.completion_event = asyncio.Event()
        self.estimated_bars = 0
        self.total_bars = 0
        self.total_ticks = 0

        # Dynamic symbol support
        self._pending_symbols: list[tuple[str, Path]] = []
        self._pending_lock = threading.Lock()
        self._current_ts: Optional[datetime] = None
        self._next_idx = 0
        self._dynamic_symbols_added: list[str] = []

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

        backtest_days = (
            (self._end_date - self._start_date).days
            if self._start_date and self._end_date else 0
        )

        for file_info in self._manifest.get("files", []):
            symbol = file_info["symbol"]
            if symbol not in self._symbols:
                continue

            file_path = self._data_dir / file_info["filename"]
            if not file_path.exists():
                logger.warning("Missing parquet file", path=str(file_path))
                continue

            self._file_entries.append((symbol, file_path))

            raw_bars = file_info.get("bar_count", 0)
            # Scale estimate by ratio of backtest range to file range
            if backtest_days > 0 and file_info.get("start_date") and file_info.get("end_date"):
                file_start = date.fromisoformat(file_info["start_date"])
                file_end = date.fromisoformat(file_info["end_date"])
                file_days = (file_end - file_start).days
                if file_days > 0:
                    scale = min(backtest_days / file_days, 1.0)
                    raw_bars = int(raw_bars * scale)

            self.estimated_bars += raw_bars

        logger.info(
            "Prepared files for replay",
            symbols=len(self._symbols),
            files=len(self._file_entries),
            estimated_bars=self.estimated_bars,
        )

    async def add_symbols(self, symbols: list[SymbolConfig]) -> None:
        """Dynamically add symbols to the replay during streaming.

        Looks up the parquet file for each symbol in the manifest and queues
        it for the main stream_ticks loop to pick up.
        """
        if not self._manifest:
            return

        # Build a quick lookup: symbol -> file_info
        manifest_lookup = {
            fi["symbol"]: fi for fi in self._manifest.get("files", [])
        }

        added = []
        for sym_config in symbols:
            sym = sym_config.symbol
            file_info = manifest_lookup.get(sym)
            if not file_info:
                logger.debug("No parquet file for dynamic symbol", symbol=sym)
                continue

            file_path = self._data_dir / file_info["filename"]
            if not file_path.exists():
                logger.debug("Missing parquet file for dynamic symbol", symbol=sym, path=str(file_path))
                continue

            with self._pending_lock:
                self._pending_symbols.append((sym, file_path))
            added.append(sym)

        if added:
            logger.info("Queued dynamic symbols for replay", symbols=added)

    def _has_pending(self) -> bool:
        with self._pending_lock:
            return len(self._pending_symbols) > 0

    def _drain_pending(self) -> list[tuple[str, Path]]:
        with self._pending_lock:
            drained = list(self._pending_symbols)
            self._pending_symbols.clear()
        return drained

    def _advance_iterator(self, it) -> Optional[tuple]:
        """Get the next bar tuple from an iterator, or None if exhausted."""
        try:
            return next(it)
        except StopIteration:
            return None

    def _fast_forward_iterator(self, it, target_ts: datetime, end_dt: Optional[datetime]) -> Optional[tuple]:
        """Advance iterator past bars before target_ts and return the first valid bar."""
        for bar_tuple in it:
            ts = bar_tuple[0]
            if end_dt and ts >= end_dt:
                return None
            if ts >= target_ts:
                return bar_tuple
        return None

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

        Uses a manual heap across per-file iterators for chronological
        ordering without loading all data into memory. Supports dynamic
        symbol injection via add_symbols() during replay.
        Yields ticks without delay. Periodically yields control to the
        event loop for fairness.
        """
        # Guard against repeated calls after replay is complete
        if self.completion_event.is_set():
            await asyncio.sleep(86400)
            return

        # Pre-compute date boundaries as UTC datetimes for fast comparison
        start_dt = (
            datetime.combine(self._start_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            if self._start_date else None
        )
        end_dt = (
            datetime.combine(self._end_date, datetime.min.time()).replace(tzinfo=timezone.utc)
            if self._end_date else None
        )

        loop = asyncio.get_running_loop()

        # Initialize heap from initial file entries
        heap: list[_HeapEntry] = []
        for symbol, path in self._file_entries:
            it = _iter_file_bars(symbol, path)
            if start_dt:
                bar_tuple = await loop.run_in_executor(
                    None, self._fast_forward_iterator, it, start_dt, end_dt
                )
            else:
                bar_tuple = self._advance_iterator(it)
            if bar_tuple is not None:
                entry = _HeapEntry(
                    timestamp=bar_tuple[0],
                    idx=self._next_idx,
                    bar_tuple=bar_tuple,
                    iterator=it,
                )
                self._next_idx += 1
                heapq.heappush(heap, entry)

        tick_count = 0
        bar_count = 0

        while heap or self._has_pending():
            # Drain any pending dynamic symbols onto the heap
            pending = self._drain_pending()
            for sym, path in pending:
                it = _iter_file_bars(sym, path)
                # Fast-forward past already-replayed timestamps
                ff_ts = self._current_ts or start_dt
                if ff_ts:
                    bar_tuple = await loop.run_in_executor(
                        None, self._fast_forward_iterator, it, ff_ts, end_dt
                    )
                else:
                    bar_tuple = self._advance_iterator(it)
                if bar_tuple is not None:
                    entry = _HeapEntry(
                        timestamp=bar_tuple[0],
                        idx=self._next_idx,
                        bar_tuple=bar_tuple,
                        iterator=it,
                    )
                    self._next_idx += 1
                    heapq.heappush(heap, entry)
                    self._dynamic_symbols_added.append(sym)
                    logger.info(
                        "Dynamic symbol joined replay",
                        symbol=sym,
                        start_ts=str(bar_tuple[0]),
                    )

            if not heap:
                # No items on heap but pending might arrive later
                await asyncio.sleep(0.1)
                continue

            # Pop the earliest entry
            entry = heapq.heappop(heap)
            bar_tuple = entry.bar_tuple
            ts, symbol, o, h, l, c, vol = bar_tuple

            # Filter bars outside the requested date range
            if end_dt and ts >= end_dt:
                # This iterator is past the end -- don't re-push
                # But keep draining the heap
                continue

            self._current_ts = ts

            ticks = self._make_ticks(symbol, ts, o, h, l, c, vol)
            bar_count += 1

            # Pace the producer to the consumers (see __init__ docstring).
            if self._throttle is not None and bar_count % 500 == 0:
                await self._throttle()

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

            # Advance the iterator and push back onto heap
            next_bar = self._advance_iterator(entry.iterator)
            if next_bar is not None:
                ts_next = next_bar[0]
                if not (end_dt and ts_next >= end_dt):
                    new_entry = _HeapEntry(
                        timestamp=ts_next,
                        idx=self._next_idx,
                        bar_tuple=next_bar,
                        iterator=entry.iterator,
                    )
                    self._next_idx += 1
                    heapq.heappush(heap, new_entry)

        if self.estimated_bars > 0:
            print(f"\rProgress: 100% ({bar_count} bars) -- replay complete.                    ", file=sys.stderr)

        self.total_bars = bar_count
        self.total_ticks = tick_count
        logger.info(
            "Replay complete",
            total_bars=self.total_bars,
            total_ticks=tick_count,
            dynamic_symbols=len(self._dynamic_symbols_added),
        )
        self.completion_event.set()

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def name(self) -> str:
        return "replay"
