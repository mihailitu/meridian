"""Trading strategies."""

from .base import BarWithIndicators, BaseStrategy, Signal
from .control import (
    ControlCommand,
    StrategyControlPublisher,
    StrategyControlSubscriber,
    StrategyState,
    StrategyStateRepository,
)
from .mean_reversion import MeanReversionStrategy
from .ml_prediction import MLPredictionStrategy
from .momentum import MomentumBreakout
from .multi_timeframe import MultiTimeframeStrategy
from .pairs import PairsStrategy

# Strategy type registry
STRATEGY_TYPES: dict[str, type[BaseStrategy]] = {
    "momentum": MomentumBreakout,
    "mean_reversion": MeanReversionStrategy,
    "multi_timeframe": MultiTimeframeStrategy,
    "pairs": PairsStrategy,
    "ml_prediction": MLPredictionStrategy,
}

__all__ = [
    "BarWithIndicators",
    "BaseStrategy",
    "ControlCommand",
    "MeanReversionStrategy",
    "MLPredictionStrategy",
    "MomentumBreakout",
    "MultiTimeframeStrategy",
    "PairsStrategy",
    "Signal",
    "StrategyControlPublisher",
    "StrategyControlSubscriber",
    "StrategyState",
    "StrategyStateRepository",
    "STRATEGY_TYPES",
]
