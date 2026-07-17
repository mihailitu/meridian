"""Base strategy interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from axtrade.common import Bar
from axtrade.indicators import MarketRegime, MarketTrend, VolatilityState
from axtrade.oms import Fill, Order, Position


class Signal(Enum):
    """Trading signal types."""

    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    CLOSE = "close"


@dataclass
class BarWithIndicators:
    """Bar data with calculated indicators."""

    bar: Bar
    sma_20: Optional[float] = None
    rsi_14: Optional[float] = None
    bb_upper: Optional[float] = None
    bb_middle: Optional[float] = None
    bb_lower: Optional[float] = None
    atr: Optional[float] = None
    regime: Optional[MarketRegime] = None
    trend: Optional[MarketTrend] = None
    volatility: Optional[VolatilityState] = None
    trend_strength: Optional[float] = None
    volatility_percentile: Optional[float] = None

    @property
    def symbol(self) -> str:
        return self.bar.symbol

    @property
    def close(self) -> float:
        return self.bar.close

    @property
    def is_trending_up(self) -> bool:
        """Check if market is in uptrend regime."""
        return self.regime == MarketRegime.TRENDING_UP

    @property
    def is_trending_down(self) -> bool:
        """Check if market is in downtrend regime."""
        return self.regime == MarketRegime.TRENDING_DOWN

    @property
    def is_high_volatility(self) -> bool:
        """Check if market volatility is high or extreme."""
        return self.volatility in (VolatilityState.HIGH, VolatilityState.EXTREME)


class BaseStrategy(ABC):
    """Abstract base class for trading strategies.

    All strategies must implement on_bar() to process incoming bars
    and optionally return orders.
    """

    def __init__(self, strategy_id: str, config: dict):
        """Initialize strategy.

        Args:
            strategy_id: Unique identifier for this strategy instance
            config: Strategy-specific configuration. Recognized common keys:
                max_positions: cap on simultaneous open positions; None = unlimited
        """
        self.strategy_id = strategy_id
        self.config = config
        self.positions: dict[str, Position] = {}
        self.enabled = True
        max_pos = config.get("max_positions")
        self.max_positions: Optional[int] = int(max_pos) if max_pos is not None else None
        # Symbols with a BUY submitted but not yet resolved (filled/rejected).
        # Async brokers (IBKR) return from submit_order before the fill
        # lands, so without this the per-strategy cap can be bypassed by
        # firing several entries for the same symbol before any of them
        # settle. Cleared on fill (update_position/clear_position) or on
        # rejection (clear_pending_open).
        self._pending_opens: set[str] = set()

    def at_capacity(self) -> bool:
        """True when the strategy has hit its own max_positions cap.

        Strategies should check this before emitting a new entry order so
        signals that would be rejected at the OMS level aren't generated.
        Counts the union of settled positions and in-flight pending opens so
        a symbol that is both (fill landed but a stale pending flag hasn't
        been cleared yet) isn't counted twice.
        """
        if self.max_positions is None:
            return False
        open_symbols = self.positions.keys() | self._pending_opens
        return len(open_symbols) >= self.max_positions

    def mark_pending_open(self, symbol: str) -> None:
        """Record a BUY order in flight for `symbol` before it resolves.

        Args:
            symbol: Symbol the in-flight entry order is for
        """
        self._pending_opens.add(symbol)

    def clear_pending_open(self, symbol: str) -> None:
        """Clear the in-flight marker for `symbol` (rejection or resolution).

        Args:
            symbol: Symbol to clear
        """
        self._pending_opens.discard(symbol)

    def has_pending_open(self, symbol: str) -> bool:
        """True while a BUY for `symbol` is in flight (submitted, unresolved).

        Args:
            symbol: Symbol to check
        """
        return symbol in self._pending_opens

    @abstractmethod
    def on_bar(self, data: BarWithIndicators) -> Optional[Order]:
        """Process a new bar and optionally generate an order.

        Args:
            data: Bar with indicator values

        Returns:
            Order to submit, or None for no action
        """
        pass

    def on_fill(self, fill: Fill) -> None:
        """Handle a fill notification.

        Override for custom fill handling logic.

        Args:
            fill: Fill information
        """
        pass

    def get_position(self, symbol: str) -> Optional[Position]:
        """Get current position for a symbol.

        Args:
            symbol: Symbol to look up

        Returns:
            Position if exists, None otherwise
        """
        return self.positions.get(symbol)

    def update_position(self, position: Position) -> None:
        """Update the local position cache.

        Args:
            position: Position to update
        """
        if position.quantity == 0 or position.closed_at is not None:
            self.positions.pop(position.symbol, None)
        else:
            self.positions[position.symbol] = position
        self._pending_opens.discard(position.symbol)

    def clear_position(self, symbol: str) -> None:
        """Clear position from local cache."""
        self.positions.pop(symbol, None)
        self._pending_opens.discard(symbol)

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy name for logging and display."""
        pass
