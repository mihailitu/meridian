"""Backtesting framework."""

from .analytics import PerformanceAnalyzer
from .broker import SimulatedBroker
from .engine import BacktestEngine
from .types import BacktestConfig, BacktestResult, EquityPoint, TradeRecord

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestResult",
    "EquityPoint",
    "PerformanceAnalyzer",
    "SimulatedBroker",
    "TradeRecord",
]
