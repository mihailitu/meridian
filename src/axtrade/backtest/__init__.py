"""Backtesting framework."""

from .analytics import PerformanceAnalyzer
from .broker import SimulatedBroker
from .data_loader import HistoricalDataLoader
from .engine import BacktestEngine
from .types import BacktestConfig, BacktestResult, EquityPoint, TradeRecord

__all__ = [
    "BacktestConfig",
    "BacktestEngine",
    "BacktestResult",
    "EquityPoint",
    "HistoricalDataLoader",
    "PerformanceAnalyzer",
    "SimulatedBroker",
    "TradeRecord",
]
