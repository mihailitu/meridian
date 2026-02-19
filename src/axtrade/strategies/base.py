"""Base strategy interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
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
            config: Strategy-specific configuration
        """
        self.strategy_id = strategy_id
        self.config = config
        self.positions: dict[str, Position] = {}
        self.enabled = True
        self._target_position_value: float | None = config.get("target_position_value")
        self._fallback_position_size = Decimal(str(config.get("position_size", 100)))

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

    def clear_position(self, symbol: str) -> None:
        """Clear position from local cache."""
        self.positions.pop(symbol, None)

    def compute_position_size(self, price: float) -> Decimal:
        """Compute position size based on target dollar value or fixed shares.

        If target_position_value is set, calculates shares to reach that dollar
        amount. Otherwise falls back to fixed position_size.

        Args:
            price: Current price of the symbol

        Returns:
            Number of shares to trade (minimum 1)
        """
        if self._target_position_value is not None and price > 0:
            shares = int(self._target_position_value / price)
            return Decimal(max(shares, 1))
        return self._fallback_position_size

    @property
    @abstractmethod
    def name(self) -> str:
        """Strategy name for logging and display."""
        pass
