"""Indicator calculation engine with rolling buffers."""

from collections import deque
from dataclasses import dataclass
from typing import Optional

from .regime import MarketRegime, MarketTrend, RegimeResult, VolatilityState, calculate_regime
from .rsi import calculate_rsi
from .sma import calculate_sma


@dataclass
class IndicatorResult:
    """Result of indicator calculations."""

    sma_20: Optional[float] = None
    rsi_14: Optional[float] = None
    regime: Optional[MarketRegime] = None
    trend: Optional[MarketTrend] = None
    volatility: Optional[VolatilityState] = None
    trend_strength: Optional[float] = None
    volatility_percentile: Optional[float] = None


class IndicatorEngine:
    """Engine for calculating indicators on streaming bar data.

    Maintains rolling price buffers per symbol/interval combination
    to enable efficient real-time indicator calculation.
    """

    def __init__(
        self,
        sma_period: int = 20,
        rsi_period: int = 14,
        regime_sma_short: int = 10,
        regime_sma_long: int = 20,
        regime_volatility_lookback: int = 20,
    ):
        """Initialize indicator engine.

        Args:
            sma_period: Period for SMA calculation
            rsi_period: Period for RSI calculation
            regime_sma_short: Short SMA period for regime trend calculation
            regime_sma_long: Long SMA period for regime trend calculation
            regime_volatility_lookback: Lookback for regime volatility calculation
        """
        self.sma_period = sma_period
        self.rsi_period = rsi_period
        self.regime_sma_short = regime_sma_short
        self.regime_sma_long = regime_sma_long
        self.regime_volatility_lookback = regime_volatility_lookback

        # Buffer needs enough data for all calculations
        self._buffer_size = max(
            sma_period,
            rsi_period + 1,
            regime_sma_long,
            regime_volatility_lookback + 1,
        ) + 10

        # Buffers keyed by (symbol, interval)
        self._close_buffers: dict[tuple[str, str], deque[float]] = {}
        self._high_buffers: dict[tuple[str, str], deque[float]] = {}
        self._low_buffers: dict[tuple[str, str], deque[float]] = {}

    def _get_key(self, symbol: str, interval: str) -> tuple[str, str]:
        """Get buffer key for symbol/interval."""
        return (symbol, interval)

    def _ensure_buffers(self, symbol: str, interval: str) -> None:
        """Ensure all buffers exist for symbol/interval."""
        key = self._get_key(symbol, interval)
        if key not in self._close_buffers:
            self._close_buffers[key] = deque(maxlen=self._buffer_size)
            self._high_buffers[key] = deque(maxlen=self._buffer_size)
            self._low_buffers[key] = deque(maxlen=self._buffer_size)

    def _get_buffer(self, symbol: str, interval: str) -> deque[float]:
        """Get or create close buffer for symbol/interval (legacy compatibility)."""
        self._ensure_buffers(symbol, interval)
        return self._close_buffers[self._get_key(symbol, interval)]

    def initialize_buffer(
        self,
        symbol: str,
        interval: str,
        historical_closes: list[float],
        historical_highs: Optional[list[float]] = None,
        historical_lows: Optional[list[float]] = None,
    ) -> None:
        """Initialize buffer with historical data.

        Args:
            symbol: Symbol identifier
            interval: Bar interval
            historical_closes: Historical close prices, oldest first
            historical_highs: Optional historical high prices
            historical_lows: Optional historical low prices
        """
        self._ensure_buffers(symbol, interval)
        key = self._get_key(symbol, interval)

        self._close_buffers[key].clear()
        self._high_buffers[key].clear()
        self._low_buffers[key].clear()

        for i, price in enumerate(historical_closes):
            self._close_buffers[key].append(price)
            if historical_highs and i < len(historical_highs):
                self._high_buffers[key].append(historical_highs[i])
            if historical_lows and i < len(historical_lows):
                self._low_buffers[key].append(historical_lows[i])

    def process_bar(
        self,
        symbol: str,
        interval: str,
        close: float,
        high: Optional[float] = None,
        low: Optional[float] = None,
    ) -> IndicatorResult:
        """Process a new bar and calculate indicators.

        Args:
            symbol: Symbol identifier
            interval: Bar interval
            close: Closing price
            high: Optional high price for regime calculation
            low: Optional low price for regime calculation

        Returns:
            Calculated indicator values including regime
        """
        self._ensure_buffers(symbol, interval)
        key = self._get_key(symbol, interval)

        # Add to buffers
        self._close_buffers[key].append(close)
        if high is not None:
            self._high_buffers[key].append(high)
        if low is not None:
            self._low_buffers[key].append(low)

        closes = list(self._close_buffers[key])

        # Calculate SMA and RSI
        sma = calculate_sma(closes, self.sma_period)
        rsi = calculate_rsi(closes, self.rsi_period)

        # Calculate regime if we have OHLC data
        regime_result: Optional[RegimeResult] = None
        if self._high_buffers[key] and self._low_buffers[key]:
            highs = list(self._high_buffers[key])
            lows = list(self._low_buffers[key])
            regime_result = calculate_regime(
                closes=closes,
                highs=highs,
                lows=lows,
                sma_short_period=self.regime_sma_short,
                sma_long_period=self.regime_sma_long,
                volatility_lookback=self.regime_volatility_lookback,
            )
        else:
            # Calculate regime with just closes
            regime_result = calculate_regime(
                closes=closes,
                sma_short_period=self.regime_sma_short,
                sma_long_period=self.regime_sma_long,
                volatility_lookback=self.regime_volatility_lookback,
            )

        return IndicatorResult(
            sma_20=round(sma, 6) if sma is not None else None,
            rsi_14=rsi,
            regime=regime_result.regime if regime_result else None,
            trend=regime_result.trend if regime_result else None,
            volatility=regime_result.volatility if regime_result else None,
            trend_strength=regime_result.trend_strength if regime_result else None,
            volatility_percentile=regime_result.volatility_percentile if regime_result else None,
        )

    def get_buffer_size(self, symbol: str, interval: str) -> int:
        """Get current buffer size for symbol/interval."""
        key = self._get_key(symbol, interval)
        if key in self._close_buffers:
            return len(self._close_buffers[key])
        return 0
