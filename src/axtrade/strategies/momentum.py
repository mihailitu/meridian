"""Momentum breakout strategy."""

from decimal import Decimal
from typing import Optional

from axtrade.indicators import MarketRegime
from axtrade.oms import Order, OrderSide, OrderType

from .base import BarWithIndicators, BaseStrategy


class MomentumBreakout(BaseStrategy):
    """Momentum breakout strategy using regime, trend strength, and RSI.

    Entry conditions (long):
    - RSI crossing above 50 (building strength)
    - Price above SMA_20 (trend confirmation)
    - Market regime is TRENDING_UP or BREAKOUT
    - Trend strength > 30

    Exit conditions:
    - RSI above overbought threshold (default 70)
    - Market regime shifts to TRENDING_DOWN
    - Stop loss triggered (default 3% below entry)
    """

    def __init__(self, strategy_id: str, config: dict):
        super().__init__(strategy_id, config)

        # Strategy parameters with defaults
        self.rsi_entry = config.get("rsi_entry", 50)
        self.rsi_overbought = config.get("rsi_overbought", 70)
        self.min_trend_strength = config.get("min_trend_strength", 30)
        self.stop_loss_pct = config.get("stop_loss_pct", 0.03)
        self.position_size = Decimal(str(config.get("position_size", 100)))
        self._prev_rsi: dict[str, float] = {}  # track previous RSI per symbol

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
            order = self._check_exit(data, position)
            self._prev_rsi[bar.symbol] = data.rsi_14
            return order

        # Check for entry
        order = self._check_entry(data)
        self._prev_rsi[bar.symbol] = data.rsi_14
        return order

    def _check_entry(self, data: BarWithIndicators) -> Optional[Order]:
        """Check for entry conditions.

        Momentum breakout: RSI crossing above entry level with price above
        SMA in a trending-up or breakout regime with sufficient trend strength.
        """
        bar = data.bar

        # Require favorable regime
        if data.regime not in (MarketRegime.TRENDING_UP, MarketRegime.BREAKOUT):
            return None

        # Require sufficient trend strength
        if data.trend_strength is None or data.trend_strength < self.min_trend_strength:
            return None

        # Price must be above SMA (uptrend confirmation)
        if bar.close <= data.sma_20:
            return None

        # RSI must be crossing above entry level (building strength)
        prev_rsi = self._prev_rsi.get(bar.symbol)
        if prev_rsi is None or prev_rsi >= self.rsi_entry:
            return None
        if data.rsi_14 < self.rsi_entry:
            return None

        return Order(
            strategy_id=self.strategy_id,
            symbol=bar.symbol,
            side=OrderSide.BUY,
            quantity=self.position_size,
            order_type=OrderType.MARKET,
        )

    def _check_exit(self, data: BarWithIndicators, position) -> Optional[Order]:
        """Check for exit conditions."""
        bar = data.bar

        # Exit on overbought RSI
        if data.rsi_14 > self.rsi_overbought:
            return self._create_close_order(bar.symbol, position.quantity)

        # Exit on regime shift to downtrend
        if data.regime == MarketRegime.TRENDING_DOWN:
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
