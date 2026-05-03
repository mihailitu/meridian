"""Momentum breakout strategy."""

from decimal import Decimal
from typing import Optional

from axtrade.indicators import MarketRegime
from axtrade.oms import Order, OrderSide, OrderType

from .base import BarWithIndicators, BaseStrategy


class MomentumBreakout(BaseStrategy):
    """Regime-aware momentum breakout strategy.

    Entry conditions (long):
    - Regime is TRENDING_UP or BREAKOUT (from IndicatorEngine)
    - Trend strength above ``trend_strength_min``
    - RSI crossing up through ``rsi_cross_level`` (prev <= level < current)
    - Close above SMA_20 (trend confirmation)
    - Strategy not at its per-strategy max_positions cap

    Exit conditions:
    - RSI above ``rsi_overbought`` (overbought reversal)
    - Regime flips to TRENDING_DOWN (trailing trend exit)
    - Stop loss triggered (default 3%)
    """

    def __init__(self, strategy_id: str, config: dict):
        super().__init__(strategy_id, config)

        self.rsi_cross_level = config.get("rsi_cross_level", 50)
        self.rsi_overbought = config.get("rsi_overbought", 70)
        self.trend_strength_min = config.get("trend_strength_min", 30.0)
        self.stop_loss_pct = config.get("stop_loss_pct", 0.03)
        self.position_size = Decimal(str(config.get("position_size", 100)))

        # Previous RSI per symbol so we can detect a level cross.
        self._prev_rsi: dict[str, float] = {}

    @property
    def name(self) -> str:
        return "MomentumBreakout"

    def on_bar(self, data: BarWithIndicators) -> Optional[Order]:
        if data.sma_20 is None or data.rsi_14 is None:
            return None

        position = self.get_position(data.symbol)

        if position and position.quantity > 0:
            order = self._check_exit(data, position)
        else:
            order = self._check_entry(data)

        # Track RSI after acting so the cross is detected on the bar where
        # the threshold is first breached.
        self._prev_rsi[data.symbol] = data.rsi_14
        return order

    def _check_entry(self, data: BarWithIndicators) -> Optional[Order]:
        if self.at_capacity():
            return None

        if data.regime not in (MarketRegime.TRENDING_UP, MarketRegime.BREAKOUT):
            return None

        if data.trend_strength is None or data.trend_strength <= self.trend_strength_min:
            return None

        if data.close <= data.sma_20:
            return None

        prev_rsi = self._prev_rsi.get(data.symbol)
        if prev_rsi is None:
            return None
        if not (prev_rsi <= self.rsi_cross_level < data.rsi_14):
            return None

        return Order(
            strategy_id=self.strategy_id,
            symbol=data.symbol,
            side=OrderSide.BUY,
            quantity=self.position_size,
            order_type=OrderType.MARKET,
        )

    def _check_exit(self, data: BarWithIndicators, position) -> Optional[Order]:
        if data.rsi_14 > self.rsi_overbought:
            return self._create_close_order(data.symbol, position.quantity)

        if data.regime == MarketRegime.TRENDING_DOWN:
            return self._create_close_order(data.symbol, position.quantity)

        if position.avg_entry_price:
            entry_price = float(position.avg_entry_price)
            loss_pct = (data.close - entry_price) / entry_price
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
