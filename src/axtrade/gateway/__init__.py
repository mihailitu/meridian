"""Gateway module for market data streaming."""

from .base import DataAdapter
from .ibkr import IBKRAdapter
from .mock import MockAdapter
from .service import GatewayService, run_gateway

__all__ = [
    "DataAdapter",
    "GatewayService",
    "IBKRAdapter",
    "MockAdapter",
    "run_gateway",
]
