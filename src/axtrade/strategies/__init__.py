"""Trading strategies."""

from .base import BarWithIndicators, BaseStrategy, Signal
from .mean_reversion import MeanReversionStrategy
from .momentum import MomentumBreakout
from .multi_timeframe import MultiTimeframeStrategy
from .pairs import PairsStrategy

# Strategy type registry
STRATEGY_TYPES: dict[str, type[BaseStrategy]] = {
    "momentum": MomentumBreakout,
    "mean_reversion": MeanReversionStrategy,
    "multi_timeframe": MultiTimeframeStrategy,
    "pairs": PairsStrategy,
}

__all__ = [
    "BarWithIndicators",
    "BaseStrategy",
    "MeanReversionStrategy",
    "MomentumBreakout",
    "MultiTimeframeStrategy",
    "PairsStrategy",
    "Signal",
    "STRATEGY_TYPES",
]
