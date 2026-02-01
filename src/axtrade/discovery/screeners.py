"""Stock screener implementations."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from .types import DiscoveredSymbol, ScreenerResult, ScreenerType


class BaseScreener(ABC):
    """Base class for stock screeners."""

    def __init__(self, name: str, screener_type: ScreenerType, params: dict = None):
        """Initialize screener.

        Args:
            name: Screener name for identification
            screener_type: Type of screener
            params: Optional screener-specific parameters
        """
        self.name = name
        self.screener_type = screener_type
        self.params = params or {}

    @abstractmethod
    async def scan(self, symbols: list[str], bars_data: dict) -> ScreenerResult:
        """Scan symbols and return matches.

        Args:
            symbols: List of symbols to scan
            bars_data: Dict mapping symbol -> list of recent bars

        Returns:
            ScreenerResult with discovered symbols
        """
        pass

    def _create_result(
        self,
        discovered: list[DiscoveredSymbol],
        total_scanned: int,
        scan_time_ms: float,
    ) -> ScreenerResult:
        """Create a standardized result object."""
        return ScreenerResult(
            screener_name=self.name,
            screener_type=self.screener_type,
            symbols=discovered,
            scan_time_ms=scan_time_ms,
            total_scanned=total_scanned,
        )


class MomentumScreener(BaseScreener):
    """Screener for momentum signals based on RSI and price action."""

    def __init__(
        self,
        name: str = "momentum",
        rsi_oversold: float = 30,
        rsi_overbought: float = 70,
        min_bars: int = 20,
    ):
        """Initialize momentum screener.

        Args:
            name: Screener name
            rsi_oversold: RSI threshold for oversold condition
            rsi_overbought: RSI threshold for overbought condition
            min_bars: Minimum number of bars required
        """
        super().__init__(
            name=name,
            screener_type=ScreenerType.MOMENTUM,
            params={
                "rsi_oversold": rsi_oversold,
                "rsi_overbought": rsi_overbought,
                "min_bars": min_bars,
            },
        )
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.min_bars = min_bars

    async def scan(self, symbols: list[str], bars_data: dict) -> ScreenerResult:
        """Scan for momentum opportunities.

        Finds symbols with:
        - RSI in oversold zone (bullish opportunity)
        - RSI in overbought zone (bearish opportunity)
        - Strong directional movement
        """
        import time

        start = time.time()
        discovered = []

        for symbol in symbols:
            bars = bars_data.get(symbol, [])
            if len(bars) < self.min_bars:
                continue

            # Get latest bar data
            latest = bars[-1]
            rsi = latest.get("rsi_14")
            close = latest.get("close")
            volume = latest.get("volume")

            if rsi is None or close is None:
                continue

            # Calculate price change
            if len(bars) >= 2:
                prev_close = bars[-2].get("close", close)
                change_pct = ((close - prev_close) / prev_close * 100) if prev_close else 0
            else:
                change_pct = 0

            score = 0
            signal_type = None

            # Check for oversold bounce opportunity
            if rsi <= self.rsi_oversold:
                score = (self.rsi_oversold - rsi) / self.rsi_oversold * 100
                signal_type = "oversold_bounce"

            # Check for overbought reversal opportunity
            elif rsi >= self.rsi_overbought:
                score = -((rsi - self.rsi_overbought) / (100 - self.rsi_overbought) * 100)
                signal_type = "overbought_reversal"

            if signal_type:
                discovered.append(
                    DiscoveredSymbol(
                        symbol=symbol,
                        source=self.name,
                        score=round(score, 2),
                        price=close,
                        volume=volume,
                        change_pct=round(change_pct, 2),
                        metadata={
                            "signal_type": signal_type,
                            "rsi": round(rsi, 2),
                        },
                    )
                )

        scan_time_ms = (time.time() - start) * 1000
        return self._create_result(discovered, len(symbols), scan_time_ms)


class VolatilityScreener(BaseScreener):
    """Screener for high volatility symbols."""

    def __init__(
        self,
        name: str = "volatility",
        min_atr_ratio: float = 2.0,
        min_bars: int = 20,
    ):
        """Initialize volatility screener.

        Args:
            name: Screener name
            min_atr_ratio: Minimum ATR as percentage of price
            min_bars: Minimum number of bars required
        """
        super().__init__(
            name=name,
            screener_type=ScreenerType.VOLATILITY,
            params={"min_atr_ratio": min_atr_ratio, "min_bars": min_bars},
        )
        self.min_atr_ratio = min_atr_ratio
        self.min_bars = min_bars

    async def scan(self, symbols: list[str], bars_data: dict) -> ScreenerResult:
        """Scan for high volatility symbols."""
        import time

        start = time.time()
        discovered = []

        for symbol in symbols:
            bars = bars_data.get(symbol, [])
            if len(bars) < self.min_bars:
                continue

            # Calculate simple volatility using high-low range
            ranges = []
            for bar in bars[-self.min_bars :]:
                high = bar.get("high")
                low = bar.get("low")
                close = bar.get("close")
                if high and low and close:
                    range_pct = (high - low) / close * 100
                    ranges.append(range_pct)

            if not ranges:
                continue

            avg_range = sum(ranges) / len(ranges)
            latest = bars[-1]
            close = latest.get("close")
            volume = latest.get("volume")

            # Calculate price change
            if len(bars) >= 2:
                prev_close = bars[-2].get("close", close)
                change_pct = ((close - prev_close) / prev_close * 100) if prev_close else 0
            else:
                change_pct = 0

            if avg_range >= self.min_atr_ratio:
                # Score based on how much volatility exceeds threshold
                score = (avg_range / self.min_atr_ratio) * 50
                discovered.append(
                    DiscoveredSymbol(
                        symbol=symbol,
                        source=self.name,
                        score=round(score, 2),
                        price=close,
                        volume=volume,
                        change_pct=round(change_pct, 2),
                        metadata={
                            "avg_range_pct": round(avg_range, 2),
                        },
                    )
                )

        scan_time_ms = (time.time() - start) * 1000
        return self._create_result(discovered, len(symbols), scan_time_ms)


class VolumeScreener(BaseScreener):
    """Screener for unusual volume activity."""

    def __init__(
        self,
        name: str = "volume",
        volume_multiplier: float = 2.0,
        min_bars: int = 20,
    ):
        """Initialize volume screener.

        Args:
            name: Screener name
            volume_multiplier: Minimum ratio vs average volume
            min_bars: Minimum number of bars for average calculation
        """
        super().__init__(
            name=name,
            screener_type=ScreenerType.VOLUME,
            params={"volume_multiplier": volume_multiplier, "min_bars": min_bars},
        )
        self.volume_multiplier = volume_multiplier
        self.min_bars = min_bars

    async def scan(self, symbols: list[str], bars_data: dict) -> ScreenerResult:
        """Scan for unusual volume spikes."""
        import time

        start = time.time()
        discovered = []

        for symbol in symbols:
            bars = bars_data.get(symbol, [])
            if len(bars) < self.min_bars:
                continue

            # Calculate average volume
            volumes = [b.get("volume", 0) for b in bars[-self.min_bars : -1]]
            if not volumes or all(v == 0 for v in volumes):
                continue

            avg_volume = sum(volumes) / len(volumes)
            if avg_volume == 0:
                continue

            latest = bars[-1]
            current_volume = latest.get("volume", 0)
            close = latest.get("close")

            volume_ratio = current_volume / avg_volume

            # Calculate price change
            if len(bars) >= 2:
                prev_close = bars[-2].get("close", close)
                change_pct = ((close - prev_close) / prev_close * 100) if prev_close else 0
            else:
                change_pct = 0

            if volume_ratio >= self.volume_multiplier:
                # Score based on volume ratio and direction of price move
                base_score = (volume_ratio / self.volume_multiplier) * 50
                direction = 1 if change_pct > 0 else -1
                score = base_score * direction

                discovered.append(
                    DiscoveredSymbol(
                        symbol=symbol,
                        source=self.name,
                        score=round(score, 2),
                        price=close,
                        volume=current_volume,
                        change_pct=round(change_pct, 2),
                        metadata={
                            "volume_ratio": round(volume_ratio, 2),
                            "avg_volume": int(avg_volume),
                        },
                    )
                )

        scan_time_ms = (time.time() - start) * 1000
        return self._create_result(discovered, len(symbols), scan_time_ms)


class TrendScreener(BaseScreener):
    """Screener for trend-following opportunities using regime detection."""

    def __init__(
        self,
        name: str = "trend",
        min_trend_strength: float = 50,
        min_bars: int = 25,
    ):
        """Initialize trend screener.

        Args:
            name: Screener name
            min_trend_strength: Minimum trend strength (0-100)
            min_bars: Minimum number of bars required
        """
        super().__init__(
            name=name,
            screener_type=ScreenerType.TREND,
            params={"min_trend_strength": min_trend_strength, "min_bars": min_bars},
        )
        self.min_trend_strength = min_trend_strength
        self.min_bars = min_bars

    async def scan(self, symbols: list[str], bars_data: dict) -> ScreenerResult:
        """Scan for strong trending symbols."""
        import time

        from axtrade.indicators import calculate_regime

        start = time.time()
        discovered = []

        for symbol in symbols:
            bars = bars_data.get(symbol, [])
            if len(bars) < self.min_bars:
                continue

            # Extract OHLC data
            closes = [b.get("close") for b in bars if b.get("close")]
            highs = [b.get("high") for b in bars if b.get("high")]
            lows = [b.get("low") for b in bars if b.get("low")]

            if len(closes) < self.min_bars:
                continue

            # Calculate regime
            regime_result = calculate_regime(closes, highs, lows)
            if not regime_result:
                continue

            if regime_result.trend_strength < self.min_trend_strength:
                continue

            latest = bars[-1]
            close = latest.get("close")
            volume = latest.get("volume")

            # Calculate price change
            if len(bars) >= 2:
                prev_close = bars[-2].get("close", close)
                change_pct = ((close - prev_close) / prev_close * 100) if prev_close else 0
            else:
                change_pct = 0

            # Score based on trend strength and direction
            direction = 1 if regime_result.trend.value == "bullish" else -1
            score = regime_result.trend_strength * direction

            discovered.append(
                DiscoveredSymbol(
                    symbol=symbol,
                    source=self.name,
                    score=round(score, 2),
                    price=close,
                    volume=volume,
                    change_pct=round(change_pct, 2),
                    metadata={
                        "regime": regime_result.regime.value,
                        "trend": regime_result.trend.value,
                        "trend_strength": regime_result.trend_strength,
                        "volatility": regime_result.volatility.value,
                    },
                )
            )

        scan_time_ms = (time.time() - start) * 1000
        return self._create_result(discovered, len(symbols), scan_time_ms)
