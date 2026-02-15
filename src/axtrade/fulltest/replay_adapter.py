"""Historical data replay adapter for full system backtest."""

import asyncio
import json
import math
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pyarrow.parquet as pq

from axtrade.common import SymbolConfig, Tick, get_logger
from axtrade.gateway.base import DataAdapter

logger = get_logger("fulltest.replay")


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


class ReplayAdapter(DataAdapter):
    """DataAdapter that replays historical parquet data as synthetic ticks.

    Converts each OHLCV bar into a sequence of ticks using price path
    interpolation:
      - Bullish bar (close >= open): O -> L -> H -> C
      - Bearish bar (close < open): O -> H -> L -> C
    """

    def __init__(
        self,
        data_dir: str,
        ticks_per_bar: int = 4,
    ):
        self._data_dir = Path(data_dir)
        self._ticks_per_bar = max(ticks_per_bar, 4)
        self._manifest: Optional[dict] = None
        self._bars: list[dict] = []
        self._symbols: list[str] = []
        self._connected = False
        self.completion_event = asyncio.Event()
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
        self._bars = []

    async def subscribe(self, symbols: list[SymbolConfig]) -> None:
        """Load parquet data for the requested symbols."""
        self._symbols = [s.symbol for s in symbols]
        self._bars = []

        for file_info in self._manifest.get("files", []):
            symbol = file_info["symbol"]
            if symbol not in self._symbols:
                continue

            file_path = self._data_dir / file_info["filename"]
            if not file_path.exists():
                logger.warning("Missing parquet file", path=str(file_path))
                continue

            table = pq.read_table(file_path)
            df = table.to_pandas()

            # Ensure UTC timestamps
            if df["timestamp"].dt.tz is None:
                df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
            else:
                df["timestamp"] = df["timestamp"].dt.tz_convert("UTC")

            for _, row in df.iterrows():
                self._bars.append({
                    "symbol": symbol,
                    "timestamp": row["timestamp"].to_pydatetime(),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": int(row["volume"]),
                })

        # Sort all bars chronologically
        self._bars.sort(key=lambda b: b["timestamp"])
        self.total_bars = len(self._bars)

        logger.info(
            "Loaded bars for replay",
            symbols=len(self._symbols),
            total_bars=self.total_bars,
        )

    def _bar_to_ticks(self, bar: dict) -> list[Tick]:
        """Convert a single OHLCV bar to synthetic ticks.

        Uses price path interpolation:
          Bullish (close >= open): O -> L -> H -> C
          Bearish (close < open):  O -> H -> L -> C
        """
        symbol = bar["symbol"]
        ts = bar["timestamp"]
        o, h, l, c = bar["open"], bar["high"], bar["low"], bar["close"]
        vol = bar["volume"]

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
        for i, price in enumerate(prices):
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

        Yields ticks without delay. Periodically yields control to the
        event loop for fairness.
        """
        tick_count = 0

        for bar in self._bars:
            ticks = self._bar_to_ticks(bar)
            for tick in ticks:
                yield tick
                tick_count += 1

                # Yield to event loop every 100 ticks
                if tick_count % 100 == 0:
                    await asyncio.sleep(0)

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
