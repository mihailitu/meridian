"""Mean reversion strategy using Bollinger Bands."""

from decimal import Decimal
from typing import Optional

from axtrade.indicators import calculate_bollinger_bands
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
    """

    def __init__(self, strategy_id: str, config: dict):
        super().__init__(strategy_id, config)

        # Bollinger Band parameters
        self.bb_period = config.get("bb_period", 20)
        self.bb_std = config.get("bb_std", 2.0)

        # RSI thresholds
        self.rsi_oversold = config.get("rsi_oversold", 35)
        self.rsi_overbought = config.get("rsi_overbought", 70)

        # Risk management
        self.stop_loss_pct = config.get("stop_loss_pct", 0.02)

        # Price buffer for Bollinger calculation
        self._price_buffer: dict[str, list[float]] = {}

    @property
    def name(self) -> str:
        return "MeanReversion"

    def _update_buffer(self, symbol: str, price: float) -> None:
        """Update price buffer for symbol."""
        if symbol not in self._price_buffer:
            self._price_buffer[symbol] = []

        self._price_buffer[symbol].append(price)

        # Keep only needed history (2x period for safety)
        max_size = self.bb_period * 2
        if len(self._price_buffer[symbol]) > max_size:
            self._price_buffer[symbol] = self._price_buffer[symbol][-max_size:]

    def _get_bollinger(self, symbol: str) -> tuple[float, float, float] | None:
        """Get current Bollinger Bands for symbol."""
        prices = self._price_buffer.get(symbol, [])
        return calculate_bollinger_bands(prices, self.bb_period, self.bb_std)

    def on_bar(self, data: BarWithIndicators) -> Optional[Order]:
        """Process bar and generate trading signals."""
        symbol = data.symbol
        price = float(data.close)

        # Update price buffer
        self._update_buffer(symbol, price)

        # Get Bollinger Bands
        bands = self._get_bollinger(symbol)
        if bands is None:
            return None

        middle, upper, lower = bands
        position = self.get_position(symbol)

        # Check for exit first if we have a position
        if position and position.quantity > 0:
            return self._check_exit(data, position, upper)

        # Check for entry
        return self._check_entry(data, lower)

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
                quantity=self.compute_position_size(price),
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
