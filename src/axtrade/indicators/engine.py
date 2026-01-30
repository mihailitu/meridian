"""Indicator calculation engine with rolling buffers."""

from collections import deque
from dataclasses import dataclass
from typing import Optional

from .rsi import calculate_rsi
from .sma import calculate_sma


@dataclass
class IndicatorResult:
    """Result of indicator calculations."""

    sma_20: Optional[float] = None
    rsi_14: Optional[float] = None


class IndicatorEngine:
    """Engine for calculating indicators on streaming bar data.

    Maintains rolling price buffers per symbol/interval combination
    to enable efficient real-time indicator calculation.
    """

    def __init__(self, sma_period: int = 20, rsi_period: int = 14):
        """Initialize indicator engine.

        Args:
            sma_period: Period for SMA calculation
            rsi_period: Period for RSI calculation
        """
        self.sma_period = sma_period
        self.rsi_period = rsi_period

        # Buffer needs enough data for RSI (which needs period + 1 prices)
        # and SMA (which needs period prices)
        self._buffer_size = max(sma_period, rsi_period + 1) + 10

        # Buffers keyed by (symbol, interval)
        self._buffers: dict[tuple[str, str], deque[float]] = {}

    def _get_key(self, symbol: str, interval: str) -> tuple[str, str]:
        """Get buffer key for symbol/interval."""
        return (symbol, interval)

    def _get_buffer(self, symbol: str, interval: str) -> deque[float]:
        """Get or create buffer for symbol/interval."""
        key = self._get_key(symbol, interval)
        if key not in self._buffers:
            self._buffers[key] = deque(maxlen=self._buffer_size)
        return self._buffers[key]

    def initialize_buffer(
        self,
        symbol: str,
        interval: str,
        historical_closes: list[float],
    ) -> None:
        """Initialize buffer with historical data.

        Args:
            symbol: Symbol identifier
            interval: Bar interval
            historical_closes: Historical close prices, oldest first
        """
        buffer = self._get_buffer(symbol, interval)
        buffer.clear()
        for price in historical_closes:
            buffer.append(price)

    def process_bar(
        self,
        symbol: str,
        interval: str,
        close: float,
    ) -> IndicatorResult:
        """Process a new bar and calculate indicators.

        Args:
            symbol: Symbol identifier
            interval: Bar interval
            close: Closing price

        Returns:
            Calculated indicator values
        """
        buffer = self._get_buffer(symbol, interval)
        buffer.append(close)

        sma = calculate_sma(buffer, self.sma_period)
        rsi = calculate_rsi(buffer, self.rsi_period)

        return IndicatorResult(
            sma_20=round(sma, 6) if sma is not None else None,
            rsi_14=rsi,
        )

    def get_buffer_size(self, symbol: str, interval: str) -> int:
        """Get current buffer size for symbol/interval."""
        key = self._get_key(symbol, interval)
        if key in self._buffers:
            return len(self._buffers[key])
        return 0
