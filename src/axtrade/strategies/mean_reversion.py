"""Mean reversion strategy using Bollinger Bands."""

from decimal import Decimal
from typing import Optional

from axtrade.indicators import MarketRegime
from axtrade.oms import Order, OrderSide, OrderType

from .base import BarWithIndicators, BaseStrategy


# Mean reversion only edges out in non-trending tape; ranging regimes from
# the IndicatorEngine are the green light.
_RANGING_REGIMES = (MarketRegime.RANGING_QUIET, MarketRegime.RANGING_VOLATILE)


class MeanReversionStrategy(BaseStrategy):
    """Mean reversion strategy using Bollinger Bands and RSI.

    Entry conditions (long):
    - Regime is RANGING_QUIET or RANGING_VOLATILE (skip trending tape)
    - Price at or below lower Bollinger Band
    - RSI below oversold threshold
    - Strategy not at its per-strategy max_positions cap

    Exit conditions:
    - Price at or above middle Bollinger Band (SMA — captures the
      reliable half of the swing instead of holding for the upper band)
    - RSI above overbought threshold (secondary)
    - Stop loss triggered (default 1.5%)

    Bollinger Bands come from the IndicatorEngine via BarWithIndicators;
    bb_period / bb_std are configured at the engine level (see
    IndicatorConfig), not per strategy.
    """

    def __init__(self, strategy_id: str, config: dict):
        super().__init__(strategy_id, config)

        self.rsi_oversold = config.get("rsi_oversold", 35)
        self.rsi_overbought = config.get("rsi_overbought", 70)

        self.stop_loss_pct = config.get("stop_loss_pct", 0.015)
        self.position_size = Decimal(str(config.get("position_size", 100)))

    @property
    def name(self) -> str:
        return "MeanReversion"

    def on_bar(self, data: BarWithIndicators) -> Optional[Order]:
        if data.bb_upper is None or data.bb_lower is None or data.bb_middle is None:
            return None

        position = self.get_position(data.symbol)

        if position and position.quantity > 0:
            return self._check_exit(data, position)

        return self._check_entry(data)

    def _check_entry(self, data: BarWithIndicators) -> Optional[Order]:
        if self.at_capacity():
            return None
        if data.regime not in _RANGING_REGIMES:
            return None
        if data.rsi_14 is None:
            return None
        if data.bb_lower is None:
            return None

        price = float(data.close)
        if price > data.bb_lower:
            return None
        if data.rsi_14 >= self.rsi_oversold:
            return None

        return Order(
            strategy_id=self.strategy_id,
            symbol=data.symbol,
            side=OrderSide.BUY,
            quantity=self.position_size,
            order_type=OrderType.MARKET,
        )

    def _check_exit(
        self, data: BarWithIndicators, position
    ) -> Optional[Order]:
        price = float(data.close)

        # Exit at middle band (SMA) — capture the dependable mean reversion,
        # not the full swing to the upper band.
        if data.bb_middle is not None and price >= data.bb_middle:
            return self._create_close_order(data.symbol, position.quantity)

        if data.rsi_14 is not None and data.rsi_14 > self.rsi_overbought:
            return self._create_close_order(data.symbol, position.quantity)

        if position.avg_entry_price:
            entry_price = float(position.avg_entry_price)
            loss_pct = (price - entry_price) / entry_price
            if loss_pct < -self.stop_loss_pct:
                return self._create_close_order(data.symbol, position.quantity)

        return None

    def _create_close_order(self, symbol: str, quantity: Decimal) -> Order:
        return Order(
            strategy_id=self.strategy_id,
            symbol=symbol,
            side=OrderSide.SELL,
            quantity=quantity,
            order_type=OrderType.MARKET,
        )
