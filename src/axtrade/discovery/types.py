"""Discovery module types."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ScreenerType(Enum):
    """Types of stock screeners."""

    MOMENTUM = "momentum"
    VOLATILITY = "volatility"
    VOLUME = "volume"
    TREND = "trend"
    BREAKOUT = "breakout"


@dataclass
class ScreenerConfig:
    """Configuration for a screener."""

    type: ScreenerType
    name: str
    enabled: bool = True
    params: dict = field(default_factory=dict)


@dataclass
class DiscoveredSymbol:
    """A symbol discovered through screening."""

    symbol: str
    source: str  # Which screener found it
    score: float  # Screening score (higher = stronger signal)
    price: Optional[float] = None
    volume: Optional[int] = None
    change_pct: Optional[float] = None
    discovered_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)

    @property
    def is_bullish(self) -> bool:
        """Check if the signal is bullish."""
        return self.score > 0

    @property
    def is_bearish(self) -> bool:
        """Check if the signal is bearish."""
        return self.score < 0


@dataclass
class ScreenerResult:
    """Result from running a screener."""

    screener_name: str
    screener_type: ScreenerType
    symbols: list[DiscoveredSymbol]
    scan_time_ms: float
    total_scanned: int
    timestamp: datetime = field(default_factory=datetime.utcnow)

    @property
    def match_count(self) -> int:
        """Number of symbols that matched the screener criteria."""
        return len(self.symbols)


@dataclass
class DiscoveryState:
    """Current state of the discovery service."""

    active_screeners: list[str]
    last_scan: Optional[datetime]
    total_discovered: int
    discovered_symbols: list[DiscoveredSymbol]
    is_scanning: bool = False
