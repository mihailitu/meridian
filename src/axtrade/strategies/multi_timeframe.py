"""Multi-timeframe trend following strategy."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from axtrade.oms import Order, OrderSide, OrderType

from .base import BarWithIndicators, BaseStrategy


class MultiTimeframeStrategy(BaseStrategy):
    """Multi-timeframe trend following strategy.

    Uses higher timeframe (aggregated from 1m bars) for trend direction
    and lower timeframe (1m) for entry timing.

    Entry conditions (long):
    - Higher timeframe trend is UP (price > SMA)
    - Lower timeframe RSI is oversold

    Exit conditions:
    - Higher timeframe trend reverses to DOWN
    - Take profit target reached
    - Stop loss triggered
    """

    def __init__(self, strategy_id: str, config: dict):
        super().__init__(strategy_id, config)

        # Trend calculation parameters
        self.trend_period = config.get("trend_period", 20)
        self.trend_interval_minutes = config.get("trend_interval_minutes", 5)

        # Entry/exit thresholds
        self.rsi_oversold = config.get("rsi_oversold", 40)
        self.rsi_overbought = config.get("rsi_overbought", 60)

        # Risk management
        self.stop_loss_pct = config.get("stop_loss_pct", 0.015)
        self.take_profit_pct = config.get("take_profit_pct", 0.03)

        # Higher timeframe data storage
        self._trend_closes: dict[str, list[float]] = {}
        self._current_htf_candle: dict[str, dict] = {}

    @property
    def name(self) -> str:
        return "MultiTimeframe"

    def _aggregate_to_htf(self, symbol: str, bar_time: datetime, close: float) -> None:
        """Aggregate 1m bars into higher timeframe candles."""
        minute = bar_time.minute
        interval = self.trend_interval_minutes

        # Initialize current HTF candle if needed
        if symbol not in self._current_htf_candle:
            self._current_htf_candle[symbol] = {
                "start_minute": (minute // interval) * interval,
                "close": close,
            }

        current = self._current_htf_candle[symbol]
        expected_start = (minute // interval) * interval

        # Check if we're in a new HTF candle
        if expected_start != current["start_minute"]:
            # Save the completed candle's close
            if symbol not in self._trend_closes:
                self._trend_closes[symbol] = []
            self._trend_closes[symbol].append(current["close"])

            # Keep only needed history
            max_size = self.trend_period * 2
            if len(self._trend_closes[symbol]) > max_size:
                self._trend_closes[symbol] = self._trend_closes[symbol][-max_size:]

            # Start new candle
            self._current_htf_candle[symbol] = {
                "start_minute": expected_start,
                "close": close,
            }
        else:
            # Update current candle's close
            current["close"] = close

    def _get_trend(self, symbol: str) -> str | None:
        """Determine trend from higher timeframe data.

        Returns:
            'up', 'down', or None if insufficient data
        """
        closes = self._trend_closes.get(symbol, [])
        if len(closes) < self.trend_period:
            return None

        # Calculate SMA on higher timeframe
        recent = closes[-self.trend_period:]
        sma = sum(recent) / len(recent)
        current = closes[-1]

        return "up" if current > sma else "down"

    def on_bar(self, data: BarWithIndicators) -> Optional[Order]:
        """Process bar and generate trading signals."""
        symbol = data.symbol
        price = float(data.close)
        bar_time = data.bar.timestamp

        # Aggregate to higher timeframe
        self._aggregate_to_htf(symbol, bar_time, price)

        # Get trend direction
        trend = self._get_trend(symbol)
        if trend is None:
            return None

        position = self.get_position(symbol)

        # Check for exit first if we have a position
        if position and position.quantity > 0:
            return self._check_exit(data, position, trend)

        # Check for entry
        return self._check_entry(data, trend)

    def _check_entry(self, data: BarWithIndicators, trend: str) -> Optional[Order]:
        """Check for entry conditions.

        Buy when trend is up and RSI is oversold on lower timeframe.
        """
        # Need RSI for entry
        if data.rsi_14 is None:
            return None

        # Entry: trend UP + RSI oversold
        if trend == "up" and data.rsi_14 < self.rsi_oversold:
            return Order(
                strategy_id=self.strategy_id,
                symbol=data.symbol,
                side=OrderSide.BUY,
                quantity=self.compute_position_size(float(data.close)),
                order_type=OrderType.MARKET,
            )

        return None

    def _check_exit(
        self, data: BarWithIndicators, position, trend: str
    ) -> Optional[Order]:
        """Check for exit conditions.

        Exit on trend reversal, take-profit, or stop-loss.
        """
        price = float(data.close)

        # Exit on trend reversal
        if trend == "down":
            return self._create_close_order(data.symbol, position.quantity)

        # Take profit and stop loss checks
        if position.avg_entry_price:
            entry_price = float(position.avg_entry_price)
            pnl_pct = (price - entry_price) / entry_price

            # Take profit
            if pnl_pct >= self.take_profit_pct:
                return self._create_close_order(data.symbol, position.quantity)

            # Stop loss
            if pnl_pct <= -self.stop_loss_pct:
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
