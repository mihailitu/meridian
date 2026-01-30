"""Bar aggregation engine."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from axtrade.common import Bar, Tick


@dataclass
class OpenBar:
    """A bar that is still being built."""

    symbol: str
    interval: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    bar_start: datetime

    def update(self, tick: Tick) -> None:
        """Update bar with new tick data."""
        self.high = max(self.high, tick.price)
        self.low = min(self.low, tick.price)
        self.close = tick.price
        if tick.volume:
            self.volume += tick.volume

    def to_bar(self) -> Bar:
        """Convert to completed Bar."""
        return Bar(
            symbol=self.symbol,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            volume=self.volume,
            timestamp=self.bar_start,
        )


def parse_interval_seconds(interval: str) -> int:
    """Parse interval string to seconds.

    Args:
        interval: Interval string (e.g., "1m", "5m", "1h")

    Returns:
        Interval in seconds
    """
    unit = interval[-1]
    value = int(interval[:-1])

    if unit == "s":
        return value
    elif unit == "m":
        return value * 60
    elif unit == "h":
        return value * 3600
    elif unit == "d":
        return value * 86400
    else:
        raise ValueError(f"Unknown interval unit: {unit}")


def get_bar_start(timestamp: datetime, interval_seconds: int) -> datetime:
    """Get the bar start time for a given timestamp.

    Bars are aligned to clock boundaries (e.g., 09:31:00, not 60s after first tick).

    Args:
        timestamp: The timestamp to align
        interval_seconds: Bar interval in seconds

    Returns:
        Bar start timestamp
    """
    ts = timestamp.timestamp()
    aligned_ts = (ts // interval_seconds) * interval_seconds
    return datetime.fromtimestamp(aligned_ts, tz=timezone.utc)


class BarEngine:
    """Aggregates ticks into OHLCV bars."""

    def __init__(self, intervals: list[str]):
        """Initialize bar engine.

        Args:
            intervals: List of bar intervals (e.g., ["1m", "5m"])
        """
        self.intervals = intervals
        self._interval_seconds = {
            interval: parse_interval_seconds(interval) for interval in intervals
        }
        # Open bars per symbol per interval
        self._open_bars: dict[str, dict[str, OpenBar]] = {}

    def process_tick(self, tick: Tick) -> list[tuple[Bar, str]]:
        """Process a tick and return any completed bars.

        Args:
            tick: Tick to process

        Returns:
            List of (bar, interval) tuples for completed bars
        """
        completed: list[tuple[Bar, str]] = []

        for interval in self.intervals:
            interval_seconds = self._interval_seconds[interval]
            bar_start = get_bar_start(tick.timestamp, interval_seconds)

            # Initialize symbol dict if needed
            if tick.symbol not in self._open_bars:
                self._open_bars[tick.symbol] = {}

            symbol_bars = self._open_bars[tick.symbol]

            if interval in symbol_bars:
                open_bar = symbol_bars[interval]

                # Check if tick belongs to a new bar period
                if bar_start > open_bar.bar_start:
                    # Complete the old bar
                    completed.append((open_bar.to_bar(), interval))
                    # Start new bar
                    symbol_bars[interval] = self._create_open_bar(
                        tick, interval, bar_start
                    )
                else:
                    # Update existing bar
                    open_bar.update(tick)
            else:
                # Create new bar for this interval
                symbol_bars[interval] = self._create_open_bar(tick, interval, bar_start)

        return completed

    def flush(self) -> list[tuple[Bar, str]]:
        """Force-complete all open bars.

        Returns:
            List of (bar, interval) tuples for all open bars
        """
        completed: list[tuple[Bar, str]] = []

        for symbol_bars in self._open_bars.values():
            for interval, open_bar in symbol_bars.items():
                completed.append((open_bar.to_bar(), interval))

        self._open_bars.clear()
        return completed

    def get_open_bar(self, symbol: str, interval: str) -> Optional[OpenBar]:
        """Get the current open bar for a symbol and interval.

        Args:
            symbol: Symbol to get bar for
            interval: Bar interval

        Returns:
            OpenBar if exists, None otherwise
        """
        if symbol in self._open_bars:
            return self._open_bars[symbol].get(interval)
        return None

    def _create_open_bar(
        self, tick: Tick, interval: str, bar_start: datetime
    ) -> OpenBar:
        """Create a new open bar from a tick."""
        return OpenBar(
            symbol=tick.symbol,
            interval=interval,
            open=tick.price,
            high=tick.price,
            low=tick.price,
            close=tick.price,
            volume=tick.volume or 0,
            bar_start=bar_start,
        )
