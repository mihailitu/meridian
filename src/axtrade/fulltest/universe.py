"""S&P 500 symbol provider for discovery scanning."""

from pathlib import Path
from typing import Optional

from axtrade.common import get_logger

logger = get_logger("fulltest.universe")

# Bundled fallback path
_SP500_CSV = Path(__file__).parent.parent.parent.parent / "data" / "sp500.csv"


class SP500SymbolProvider:
    """Provides S&P 500 constituent symbols.

    Fetches from Wikipedia on first call, falls back to bundled CSV.
    Implements the SymbolProvider protocol.
    """

    def __init__(self, csv_path: Optional[Path] = None):
        self._csv_path = csv_path or _SP500_CSV
        self._symbols: Optional[list[str]] = None

    async def get_symbols(self) -> list[str]:
        """Return list of S&P 500 ticker symbols."""
        if self._symbols is not None:
            return self._symbols

        # Try Wikipedia first
        symbols = self._fetch_from_wikipedia()
        if symbols:
            self._symbols = symbols
            logger.info("Loaded S&P 500 from Wikipedia", count=len(symbols))
            return self._symbols

        # Fall back to CSV
        symbols = self._load_from_csv()
        if symbols:
            self._symbols = symbols
            logger.info("Loaded S&P 500 from CSV", count=len(symbols))
            return self._symbols

        logger.warning("No S&P 500 data available")
        self._symbols = []
        return self._symbols

    def _fetch_from_wikipedia(self) -> Optional[list[str]]:
        """Fetch S&P 500 list from Wikipedia."""
        try:
            import pandas as pd

            tables = pd.read_html(
                "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            )
            if not tables:
                return None

            df = tables[0]
            # The ticker column is typically "Symbol"
            col = None
            for candidate in ["Symbol", "Ticker", "Ticker symbol"]:
                if candidate in df.columns:
                    col = candidate
                    break

            if col is None:
                return None

            symbols = df[col].str.strip().str.replace(".", "-", regex=False).tolist()
            return sorted(symbols)
        except Exception as e:
            logger.debug("Wikipedia fetch failed", error=str(e))
            return None

    def _load_from_csv(self) -> Optional[list[str]]:
        """Load symbols from bundled CSV file."""
        if not self._csv_path.exists():
            return None

        try:
            symbols = []
            with open(self._csv_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        # CSV may have header or just tickers
                        symbol = line.split(",")[0].strip()
                        if symbol and symbol != "Symbol":
                            symbols.append(symbol)
            return sorted(symbols)
        except Exception as e:
            logger.debug("CSV load failed", error=str(e))
            return None
