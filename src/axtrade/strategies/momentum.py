"""Momentum breakout strategy."""

from decimal import Decimal
from typing import Optional

from axtrade.oms import Order, OrderSide, OrderType

from .base import BarWithIndicators, BaseStrategy


class MomentumBreakout(BaseStrategy):
    """Momentum breakout strategy using RSI and price action.

    Entry conditions (long):
    - RSI below oversold threshold (default 40)
    - Price above SMA_20 (trend confirmation)

    Exit conditions:
    - RSI above overbought threshold (default 70)
    - Price below SMA_20 (trend reversal)
    - Stop loss triggered (default 2% below entry)
    """

    def __init__(self, strategy_id: str, config: dict):
        super().__init__(strategy_id, config)

        # Strategy parameters with defaults
        self.rsi_oversold = config.get("rsi_oversold", 40)
        self.rsi_overbought = config.get("rsi_overbought", 70)
        self.stop_loss_pct = config.get("stop_loss_pct", 0.02)
        self.position_size = Decimal(str(config.get("position_size", 100)))

    @property
    def name(self) -> str:
        return "MomentumBreakout"

    def on_bar(self, data: BarWithIndicators) -> Optional[Order]:
        """Process bar and generate trading signals."""
        bar = data.bar
        position = self.get_position(bar.symbol)

        # Need indicators to make decisions
        if data.sma_20 is None or data.rsi_14 is None:
            return None

        # Check for exit first if we have a position
        if position and position.quantity > 0:
            return self._check_exit(data, position)

        # Check for entry
        return self._check_entry(data)

    def _check_entry(self, data: BarWithIndicators) -> Optional[Order]:
        """Check for entry conditions."""
        bar = data.bar

        # Long entry conditions:
        # 1. RSI is oversold (below threshold)
        # 2. Price is above SMA (uptrend)
        if data.rsi_14 < self.rsi_oversold and bar.close > data.sma_20:
            return Order(
                strategy_id=self.strategy_id,
                symbol=bar.symbol,
                side=OrderSide.BUY,
                quantity=self.position_size,
                order_type=OrderType.MARKET,
            )

        return None

    def _check_exit(self, data: BarWithIndicators, position) -> Optional[Order]:
        """Check for exit conditions."""
        bar = data.bar

        # Exit on overbought RSI
        if data.rsi_14 > self.rsi_overbought:
            return self._create_close_order(bar.symbol, position.quantity)

        # Exit on trend reversal (price below SMA)
        if bar.close < data.sma_20:
            return self._create_close_order(bar.symbol, position.quantity)

        # Stop loss check
        if position.avg_entry_price:
            entry_price = float(position.avg_entry_price)
            loss_pct = (bar.close - entry_price) / entry_price
            if loss_pct < -self.stop_loss_pct:
                return self._create_close_order(bar.symbol, position.quantity)

        return None

    def _create_close_order(self, symbol: str, quantity: Decimal) -> Order:
        """Create an order to close the position."""
        return Order(
            strategy_id=self.strategy_id,
            symbol=symbol,
            side=OrderSide.SELL,
            quantity=quantity,
            order_type=OrderType.MARKET,
        )
