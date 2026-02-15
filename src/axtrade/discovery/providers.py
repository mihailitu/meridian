"""Symbol providers for discovery scanning."""

from typing import Protocol, runtime_checkable

from axtrade.common import Config, get_logger


@runtime_checkable
class SymbolProvider(Protocol):
    """Protocol for providing symbols to scan.

    Implement this to add new symbol sources (e.g. IBKR scanner,
    Alpaca movers API).
    """

    async def get_symbols(self) -> list[str]:
        """Return list of ticker symbols to scan."""
        ...


class ConfigSymbolProvider:
    """Provides symbols from the gateway configuration."""

    def __init__(self, config: Config):
        self._config = config
        self._logger = get_logger("config_symbol_provider")

    async def get_symbols(self) -> list[str]:
        symbols = [s.symbol for s in self._config.gateway.symbols]
        self._logger.debug("Loaded symbols from config", count=len(symbols))
        return symbols
