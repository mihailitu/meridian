"""Feature extraction for ML models."""

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FeatureSet:
    """A set of features extracted from bar data."""

    returns: float  # Recent price returns
    volatility: float  # Price volatility
    momentum: float  # Momentum indicator
    rsi: float  # RSI value (0-100)
    trend_strength: float  # Trend strength (0-100)
    volume_ratio: float  # Volume vs average
    price_position: float  # Position in recent range (0-1)
    sma_distance: float  # Distance from SMA (percentage)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "returns": self.returns,
            "volatility": self.volatility,
            "momentum": self.momentum,
            "rsi": self.rsi,
            "trend_strength": self.trend_strength,
            "volume_ratio": self.volume_ratio,
            "price_position": self.price_position,
            "sma_distance": self.sma_distance,
        }

    def to_vector(self, feature_names: list[str]) -> list[float]:
        """Convert to feature vector for model input."""
        all_features = self.to_dict()
        return [all_features.get(name, 0.0) for name in feature_names]


class FeatureExtractor:
    """Extracts features from bar data for ML models."""

    def __init__(self, lookback_periods: int = 20):
        """Initialize feature extractor.

        Args:
            lookback_periods: Number of periods to look back for calculations
        """
        self.lookback_periods = lookback_periods

    def extract(self, bars: list[dict]) -> Optional[FeatureSet]:
        """Extract features from a list of bars.

        Args:
            bars: List of bar dictionaries with OHLCV data

        Returns:
            FeatureSet if enough data, None otherwise
        """
        if len(bars) < self.lookback_periods:
            return None

        # Use most recent bars
        recent_bars = bars[-self.lookback_periods:]

        # Extract price and volume data
        closes = [float(b.get("close", 0)) for b in recent_bars]
        highs = [float(b.get("high", 0)) for b in recent_bars]
        lows = [float(b.get("low", 0)) for b in recent_bars]
        volumes = [int(b.get("volume", 0)) for b in recent_bars]

        if not all(closes) or closes[-1] == 0:
            return None

        # Calculate features
        returns = self._calculate_returns(closes)
        volatility = self._calculate_volatility(closes)
        momentum = self._calculate_momentum(closes)
        rsi = self._calculate_rsi(closes)
        trend_strength = self._calculate_trend_strength(closes)
        volume_ratio = self._calculate_volume_ratio(volumes)
        price_position = self._calculate_price_position(closes, highs, lows)
        sma_distance = self._calculate_sma_distance(closes)

        return FeatureSet(
            returns=returns,
            volatility=volatility,
            momentum=momentum,
            rsi=rsi,
            trend_strength=trend_strength,
            volume_ratio=volume_ratio,
            price_position=price_position,
            sma_distance=sma_distance,
        )

    def _calculate_returns(self, closes: list[float]) -> float:
        """Calculate recent price returns (percentage)."""
        if len(closes) < 2 or closes[-2] == 0:
            return 0.0
        return ((closes[-1] / closes[-2]) - 1) * 100

    def _calculate_volatility(self, closes: list[float]) -> float:
        """Calculate price volatility (standard deviation of returns)."""
        if len(closes) < 3:
            return 0.0

        returns = []
        for i in range(1, len(closes)):
            if closes[i - 1] != 0:
                returns.append((closes[i] / closes[i - 1]) - 1)

        if not returns:
            return 0.0

        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        return math.sqrt(variance) * 100  # As percentage

    def _calculate_momentum(self, closes: list[float]) -> float:
        """Calculate momentum (rate of change over lookback period)."""
        if len(closes) < self.lookback_periods or closes[0] == 0:
            return 0.0
        return ((closes[-1] / closes[0]) - 1) * 100

    def _calculate_rsi(self, closes: list[float], period: int = 14) -> float:
        """Calculate RSI indicator."""
        if len(closes) < period + 1:
            return 50.0  # Neutral

        gains = []
        losses = []

        for i in range(1, len(closes)):
            change = closes[i] - closes[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))

        if len(gains) < period:
            return 50.0

        # Use recent periods
        recent_gains = gains[-period:]
        recent_losses = losses[-period:]

        avg_gain = sum(recent_gains) / period
        avg_loss = sum(recent_losses) / period

        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _calculate_trend_strength(self, closes: list[float]) -> float:
        """Calculate trend strength (0-100)."""
        if len(closes) < 10:
            return 50.0

        # Calculate short and long SMAs
        short_period = min(5, len(closes) // 2)
        long_period = min(10, len(closes))

        short_sma = sum(closes[-short_period:]) / short_period
        long_sma = sum(closes[-long_period:]) / long_period

        if long_sma == 0:
            return 50.0

        # Trend strength based on SMA divergence
        divergence = ((short_sma / long_sma) - 1) * 100
        # Scale to 0-100 range (divergence of +/-5% = 0/100)
        strength = 50 + (divergence * 10)
        return max(0, min(100, strength))

    def _calculate_volume_ratio(self, volumes: list[float]) -> float:
        """Calculate current volume vs average."""
        if len(volumes) < 2:
            return 1.0

        avg_volume = sum(volumes[:-1]) / (len(volumes) - 1)
        if avg_volume == 0:
            return 1.0

        return volumes[-1] / avg_volume

    def _calculate_price_position(
        self, closes: list[float], highs: list[float], lows: list[float]
    ) -> float:
        """Calculate price position within recent range (0-1)."""
        if not closes or not highs or not lows:
            return 0.5

        period_high = max(highs)
        period_low = min(lows)

        if period_high == period_low:
            return 0.5

        return (closes[-1] - period_low) / (period_high - period_low)

    def _calculate_sma_distance(self, closes: list[float]) -> float:
        """Calculate distance from SMA (percentage)."""
        if not closes:
            return 0.0

        sma = sum(closes) / len(closes)
        if sma == 0:
            return 0.0

        return ((closes[-1] / sma) - 1) * 100
