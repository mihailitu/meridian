"""Abstract data adapter interface."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

from ..common import SymbolConfig, Tick


class DataAdapter(ABC):
    """Abstract base class for data adapters.

    All data adapters (mock, IBKR, etc.) must implement this interface
    to ensure consistent behavior across different data sources.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the data source."""
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """Disconnect from the data source."""
        pass

    @abstractmethod
    async def subscribe(self, symbols: list[SymbolConfig]) -> None:
        """Subscribe to market data for the given symbols.

        Args:
            symbols: List of symbols to subscribe to
        """
        pass

    @abstractmethod
    def stream_ticks(self) -> AsyncIterator[Tick]:
        """Stream ticks as an async generator.

        Yields:
            Tick objects as they arrive
        """
        pass

    @property
    @abstractmethod
    def connected(self) -> bool:
        """Check if adapter is connected."""
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Return adapter name."""
        pass
