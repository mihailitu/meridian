"""Symbol universe providers for backtesting and discovery."""

from pathlib import Path
from typing import Optional

from axtrade.common import get_logger

logger = get_logger("fulltest.universe")

# Bundled fallback paths
_DATA_DIR = Path(__file__).parent.parent.parent.parent / "data"
_SP500_CSV = _DATA_DIR / "sp500.csv"
_SP1500_CSV = _DATA_DIR / "sp1500.csv"

# Wikipedia URLs for S&P index constituents
_WIKI_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
_WIKI_SP400 = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
_WIKI_SP600 = "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"


def _load_csv(csv_path: Path) -> Optional[list[str]]:
    """Load symbols from a CSV file with a Symbol header."""
    if not csv_path.exists():
        return None
    try:
        symbols = []
        with open(csv_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    symbol = line.split(",")[0].strip()
                    if symbol and symbol != "Symbol":
                        symbols.append(symbol)
        return sorted(symbols)
    except Exception as e:
        logger.debug("CSV load failed", path=str(csv_path), error=str(e))
        return None


def _fetch_wiki_table(url: str) -> Optional[list[str]]:
    """Fetch ticker symbols from a Wikipedia index table."""
    try:
        import pandas as pd

        tables = pd.read_html(url)
        if not tables:
            return None

        df = tables[0]
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
        logger.debug("Wikipedia fetch failed", url=url, error=str(e))
        return None


class SP500SymbolProvider:
    """Provides S&P 500 constituent symbols.

    Fetches from Wikipedia on first call, falls back to bundled CSV.
    Implements the SymbolProvider protocol.
    """

    def __init__(self, csv_path: Optional[Path] = None):
        self._csv_path = csv_path or _SP500_CSV
        self._symbols: Optional[list[str]] = None

    async def get_symbols(self) -> list[str]:
        if self._symbols is not None:
            return self._symbols

        symbols = _fetch_wiki_table(_WIKI_SP500)
        if symbols:
            self._symbols = symbols
            logger.info("Loaded S&P 500 from Wikipedia", count=len(symbols))
            return self._symbols

        symbols = _load_csv(self._csv_path)
        if symbols:
            self._symbols = symbols
            logger.info("Loaded S&P 500 from CSV", count=len(symbols))
            return self._symbols

        logger.warning("No S&P 500 data available")
        self._symbols = []
        return self._symbols


class SP1500SymbolProvider:
    """Provides S&P 1500 constituent symbols (S&P 500 + MidCap 400 + SmallCap 600).

    Fetches all three indices from Wikipedia, deduplicates, and merges.
    Falls back to bundled data/sp1500.csv.
    Implements the SymbolProvider protocol.
    """

    def __init__(self, csv_path: Optional[Path] = None):
        self._csv_path = csv_path or _SP1500_CSV
        self._symbols: Optional[list[str]] = None

    async def get_symbols(self) -> list[str]:
        if self._symbols is not None:
            return self._symbols

        # Try fetching all three from Wikipedia
        sp500 = _fetch_wiki_table(_WIKI_SP500)
        sp400 = _fetch_wiki_table(_WIKI_SP400)
        sp600 = _fetch_wiki_table(_WIKI_SP600)

        if sp500 and sp400 and sp600:
            merged = sorted(set(sp500 + sp400 + sp600))
            self._symbols = merged
            logger.info(
                "Loaded S&P 1500 from Wikipedia",
                sp500=len(sp500),
                sp400=len(sp400),
                sp600=len(sp600),
                total=len(merged),
            )
            return self._symbols

        # Fall back to CSV
        symbols = _load_csv(self._csv_path)
        if symbols:
            self._symbols = symbols
            logger.info("Loaded S&P 1500 from CSV", count=len(symbols))
            return self._symbols

        logger.warning("No S&P 1500 data available")
        self._symbols = []
        return self._symbols
