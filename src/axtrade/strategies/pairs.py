"""Pairs trading strategy for correlated symbols."""

from decimal import Decimal
from typing import Optional

from axtrade.oms import Order, OrderSide, OrderType

from .base import BarWithIndicators, BaseStrategy


class PairsStrategy(BaseStrategy):
    """Pairs trading strategy on correlated symbols.

    Trades mean reversion of the price ratio between two correlated symbols.
    Uses z-score to identify when the ratio has deviated significantly
    from its historical mean.

    Entry conditions:
    - Z-score of ratio < -entry_zscore: Go long symbol A (ratio too low)
    - Z-score of ratio > entry_zscore: Go short symbol A (ratio too high)

    Exit conditions:
    - Z-score returns to within exit_zscore of mean
    - Stop loss triggered

    Note: This simplified implementation only trades one leg (symbol A).
    A full pairs implementation would trade both legs simultaneously.
    """

    def __init__(self, strategy_id: str, config: dict):
        super().__init__(strategy_id, config)

        # Symbol pair configuration
        self.symbol_a = config.get("symbol_a", "AAPL")
        self.symbol_b = config.get("symbol_b", "MSFT")

        # Z-score parameters
        self.lookback = config.get("lookback", 20)
        self.entry_zscore = config.get("entry_zscore", 2.0)
        self.exit_zscore = config.get("exit_zscore", 0.5)

        # Risk management
        self.stop_loss_pct = config.get("stop_loss_pct", 0.03)
        self.position_size = Decimal(str(config.get("position_size", 50)))

        # Price history
        self._prices_a: list[float] = []
        self._prices_b: list[float] = []

        # Track spread position direction
        self._spread_direction: str | None = None  # "long" or "short"

    @property
    def name(self) -> str:
        return f"Pairs({self.symbol_a}/{self.symbol_b})"

    def _update_prices(self, symbol: str, price: float) -> None:
        """Update price history for symbol."""
        max_size = self.lookback * 2

        if symbol == self.symbol_a:
            self._prices_a.append(price)
            if len(self._prices_a) > max_size:
                self._prices_a = self._prices_a[-max_size:]
        elif symbol == self.symbol_b:
            self._prices_b.append(price)
            if len(self._prices_b) > max_size:
                self._prices_b = self._prices_b[-max_size:]

    def _calculate_zscore(self) -> float | None:
        """Calculate z-score of the current price ratio.

        Returns:
            Z-score value, or None if insufficient data
        """
        if (len(self._prices_a) < self.lookback or
                len(self._prices_b) < self.lookback):
            return None

        # Calculate historical ratios
        recent_a = self._prices_a[-self.lookback:]
        recent_b = self._prices_b[-self.lookback:]

        ratios = [a / b for a, b in zip(recent_a, recent_b)]

        # Calculate mean and std dev
        mean = sum(ratios) / len(ratios)
        variance = sum((r - mean) ** 2 for r in ratios) / len(ratios)
        std = variance ** 0.5

        if std == 0:
            return None

        # Current ratio z-score
        current_ratio = self._prices_a[-1] / self._prices_b[-1]
        return (current_ratio - mean) / std

    def on_bar(self, data: BarWithIndicators) -> Optional[Order]:
        """Process bar and generate trading signals.

        Note: This strategy listens to bars from both symbols but only
        generates orders for symbol_a.
        """
        symbol = data.symbol
        price = float(data.close)

        # Update price buffers
        self._update_prices(symbol, price)

        # Only generate signals when processing symbol_a
        if symbol != self.symbol_a:
            return None

        # Calculate z-score
        zscore = self._calculate_zscore()
        if zscore is None:
            return None

        position = self.get_position(self.symbol_a)

        # Check for exit first if we have a position
        if position and position.quantity > 0:
            return self._check_exit(data, position, zscore)

        # Check for entry
        return self._check_entry(data, zscore)

    def _check_entry(
        self, data: BarWithIndicators, zscore: float
    ) -> Optional[Order]:
        """Check for entry conditions based on z-score."""
        # No position and no spread direction means we can enter

        if self._spread_direction is not None:
            return None

        # Long entry: z-score very negative (ratio too low, expect it to rise)
        if zscore < -self.entry_zscore:
            self._spread_direction = "long"
            return Order(
                strategy_id=self.strategy_id,
                symbol=self.symbol_a,
                side=OrderSide.BUY,
                quantity=self.position_size,
                order_type=OrderType.MARKET,
            )

        # Short entry: z-score very positive (ratio too high, expect it to fall)
        # Note: Simplified - not implementing short selling for now
        # if zscore > self.entry_zscore:
        #     self._spread_direction = "short"
        #     return Order(...)

        return None

    def _check_exit(
        self, data: BarWithIndicators, position, zscore: float
    ) -> Optional[Order]:
        """Check for exit conditions."""
        price = float(data.close)

        # Exit when z-score returns to normal range
        if self._spread_direction == "long" and abs(zscore) < self.exit_zscore:
            self._spread_direction = None
            return self._create_close_order(position.quantity)

        # Stop loss check
        if position.avg_entry_price:
            entry_price = float(position.avg_entry_price)
            pnl_pct = (price - entry_price) / entry_price

            if pnl_pct <= -self.stop_loss_pct:
                self._spread_direction = None
                return self._create_close_order(position.quantity)

        return None

    def _create_close_order(self, quantity: Decimal) -> Order:
        """Create an order to close the position."""
        return Order(
            strategy_id=self.strategy_id,
            symbol=self.symbol_a,
            side=OrderSide.SELL,
            quantity=quantity,
            order_type=OrderType.MARKET,
        )
