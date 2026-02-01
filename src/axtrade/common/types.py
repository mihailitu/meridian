"""Shared data types for axtrade."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Optional


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Tick:
    """A single price tick."""

    symbol: str
    price: float
    timestamp: datetime = field(default_factory=_utcnow)
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[int] = None
    market: str = "us"  # Market identifier (us, eu, asia, crypto, forex)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "symbol": self.symbol,
            "price": str(self.price),
            "timestamp": self.timestamp.isoformat(),
            "bid": str(self.bid) if self.bid else "",
            "ask": str(self.ask) if self.ask else "",
            "volume": str(self.volume) if self.volume else "",
            "market": self.market,
        }

    @property
    def change(self) -> Optional[float]:
        """Price change (requires previous tick for calculation)."""
        return None


@dataclass(frozen=True)
class Bar:
    """OHLCV bar data."""

    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    timestamp: datetime
    interval: str = "1m"  # Bar interval (1m, 5m, etc.)
    market: str = "us"  # Market identifier (us, eu, asia, crypto, forex)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "symbol": self.symbol,
            "open": str(self.open),
            "high": str(self.high),
            "low": str(self.low),
            "close": str(self.close),
            "volume": str(self.volume),
            "timestamp": self.timestamp.isoformat(),
            "interval": self.interval,
            "market": self.market,
        }


@dataclass
class SymbolConfig:
    """Configuration for a tradeable symbol."""

    symbol: str
    base_price: float
    exchange: str = "SMART"
    currency: str = "USD"
    sec_type: str = "STK"
