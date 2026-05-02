"""Mean reversion strategy using Bollinger Bands."""

from decimal import Decimal
from typing import Optional

from axtrade.oms import Order, OrderSide, OrderType

from .base import BarWithIndicators, BaseStrategy


class MeanReversionStrategy(BaseStrategy):
    """Mean reversion strategy using Bollinger Bands and RSI.

    Entry conditions (long):
    - Price at or below lower Bollinger Band
    - RSI below oversold threshold

    Exit conditions:
    - Price at or above upper Bollinger Band
    - RSI above overbought threshold
    - Stop loss triggered

    Bollinger Bands come from the IndicatorEngine via BarWithIndicators;
    bb_period / bb_std are configured at the engine level (see
    IndicatorConfig), not per strategy.
    """

    def __init__(self, strategy_id: str, config: dict):
        super().__init__(strategy_id, config)

        # RSI thresholds
        self.rsi_oversold = config.get("rsi_oversold", 35)
        self.rsi_overbought = config.get("rsi_overbought", 70)

        # Risk management
        self.stop_loss_pct = config.get("stop_loss_pct", 0.02)
        self.position_size = Decimal(str(config.get("position_size", 100)))

    @property
    def name(self) -> str:
        return "MeanReversion"

    def on_bar(self, data: BarWithIndicators) -> Optional[Order]:
        """Process bar and generate trading signals."""
        # Wait for the indicator engine to have warmed up.
        if data.bb_upper is None or data.bb_lower is None:
            return None

        position = self.get_position(data.symbol)

        # Check for exit first if we have a position
        if position and position.quantity > 0:
            return self._check_exit(data, position, data.bb_upper)

        # Check for entry
        return self._check_entry(data, data.bb_lower)

    def _check_entry(
        self, data: BarWithIndicators, lower_band: float
    ) -> Optional[Order]:
        """Check for entry conditions.

        Buy when price touches lower band and RSI is oversold.
        """
        price = float(data.close)

        # Need RSI for confirmation
        if data.rsi_14 is None:
            return None

        # Entry: price at/below lower band + RSI oversold
        if price <= lower_band and data.rsi_14 < self.rsi_oversold:
            return Order(
                strategy_id=self.strategy_id,
                symbol=data.symbol,
                side=OrderSide.BUY,
                quantity=self.position_size,
                order_type=OrderType.MARKET,
            )

        return None

    def _check_exit(
        self, data: BarWithIndicators, position, upper_band: float
    ) -> Optional[Order]:
        """Check for exit conditions.

        Sell when price reaches upper band, RSI overbought, or stop-loss.
        """
        price = float(data.close)

        # Exit on price at/above upper band
        if price >= upper_band:
            return self._create_close_order(data.symbol, position.quantity)

        # Exit on overbought RSI
        if data.rsi_14 is not None and data.rsi_14 > self.rsi_overbought:
            return self._create_close_order(data.symbol, position.quantity)

        # Stop loss check
        if position.avg_entry_price:
            entry_price = float(position.avg_entry_price)
            loss_pct = (price - entry_price) / entry_price
            if loss_pct < -self.stop_loss_pct:
                return self._create_close_order(data.symbol, position.quantity)

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
