"""Trading strategies."""

from .base import BarWithIndicators, BaseStrategy, Signal
from .control import (
    ControlCommand,
    StrategyControlPublisher,
    StrategyControlSubscriber,
    StrategyState,
    StrategyStateRepository,
)
from .buy_hold import BuyHoldStrategy
from .discovery_momentum import DiscoveryMomentumStrategy
from .mean_reversion import MeanReversionStrategy
from .ml_prediction import MLPredictionStrategy
from .momentum import MomentumBreakout
from .multi_timeframe import MultiTimeframeStrategy
from .pairs import PairsStrategy

# Strategy type registry
STRATEGY_TYPES: dict[str, type[BaseStrategy]] = {
    "buy_hold": BuyHoldStrategy,
    "momentum": MomentumBreakout,
    "mean_reversion": MeanReversionStrategy,
    "multi_timeframe": MultiTimeframeStrategy,
    "pairs": PairsStrategy,
    "ml_prediction": MLPredictionStrategy,
    "discovery_momentum": DiscoveryMomentumStrategy,
}

__all__ = [
    "BarWithIndicators",
    "BaseStrategy",
    "BuyHoldStrategy",
    "ControlCommand",
    "DiscoveryMomentumStrategy",
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
