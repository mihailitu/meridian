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
from .momentum import MomentumBreakout
from .multi_timeframe import MultiTimeframeStrategy
from .overnight_reversal import OvernightReversalStrategy
from .pairs import PairsStrategy

# Strategy type registry
STRATEGY_TYPES: dict[str, type[BaseStrategy]] = {
    "buy_hold": BuyHoldStrategy,
    "momentum": MomentumBreakout,
    "mean_reversion": MeanReversionStrategy,
    "multi_timeframe": MultiTimeframeStrategy,
    "pairs": PairsStrategy,
    "discovery_momentum": DiscoveryMomentumStrategy,
    "overnight_reversal": OvernightReversalStrategy,
}

__all__ = [
    "BarWithIndicators",
    "BaseStrategy",
    "BuyHoldStrategy",
    "ControlCommand",
    "DiscoveryMomentumStrategy",
    "MeanReversionStrategy",
    "MomentumBreakout",
    "MultiTimeframeStrategy",
    "OvernightReversalStrategy",
    "PairsStrategy",
    "Signal",
    "StrategyControlPublisher",
    "StrategyControlSubscriber",
    "StrategyState",
    "StrategyStateRepository",
    "STRATEGY_TYPES",
]
