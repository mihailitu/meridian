"""Mock data adapter for testing."""

import asyncio
import random
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from ..common import MockConfig, SymbolConfig, Tick
from .base import DataAdapter


class MockAdapter(DataAdapter):
    """Mock adapter that generates simulated price data.

    Useful for testing and development without requiring
    a connection to a real data source.
    """

    def __init__(self, config: MockConfig):
        """Initialize mock adapter.

        Args:
            config: Mock adapter configuration
        """
        self.config = config
        self._connected = False
        self._symbols: list[SymbolConfig] = []
        self._prices: dict[str, float] = {}
        self._running = False

    async def connect(self) -> None:
        """Simulate connection."""
        self._connected = True

    async def disconnect(self) -> None:
        """Simulate disconnection."""
        self._running = False
        self._connected = False

    async def subscribe(self, symbols: list[SymbolConfig]) -> None:
        """Subscribe to symbols and initialize prices.

        Args:
            symbols: List of symbols to track
        """
        self._symbols = symbols
        self._prices = {s.symbol: s.base_price for s in symbols}

    async def add_symbols(self, symbols: list[SymbolConfig]) -> None:
        """Dynamically subscribe to additional symbols."""
        existing = {s.symbol for s in self._symbols}
        for s in symbols:
            if s.symbol not in existing:
                self._symbols.append(s)
                self._prices[s.symbol] = s.base_price

    async def remove_symbols(self, symbols: list[str]) -> None:
        """Dynamically unsubscribe from symbols."""
        remove_set = set(symbols)
        self._symbols = [s for s in self._symbols if s.symbol not in remove_set]
        for sym in symbols:
            self._prices.pop(sym, None)

    async def stream_ticks(self) -> AsyncIterator[Tick]:
        """Generate simulated ticks.

        Yields:
            Simulated Tick objects at configured interval
        """
        self._running = True
        interval = self.config.tick_interval_ms / 1000.0

        while self._running and self._connected:
            for symbol_config in self._symbols:
                symbol = symbol_config.symbol
                current_price = self._prices[symbol]

                change = random.gauss(0, self.config.volatility) * current_price
                new_price = round(current_price + change, 2)
                new_price = max(0.01, new_price)

                self._prices[symbol] = new_price

                spread = round(new_price * 0.0001, 2)
                bid = round(new_price - spread, 2)
                ask = round(new_price + spread, 2)

                tick = Tick(
                    symbol=symbol,
                    price=new_price,
                    timestamp=datetime.now(UTC),
                    bid=bid,
                    ask=ask,
                    volume=random.randint(100, 10000),
                )

                yield tick

            await asyncio.sleep(interval)

    @property
    def connected(self) -> bool:
        """Check if adapter is connected."""
        return self._connected

    @property
    def name(self) -> str:
        """Return adapter name."""
        return "mock"

    def get_price(self, symbol: str) -> float:
        """Get current price for a symbol.

        Args:
            symbol: Symbol to get price for

        Returns:
            Current simulated price
        """
        return self._prices.get(symbol, 0.0)
