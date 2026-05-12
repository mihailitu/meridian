"""Multi-timeframe trend following strategy."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from axtrade.indicators import MarketRegime
from axtrade.oms import Order, OrderSide, OrderType

from .base import BarWithIndicators, BaseStrategy


class MultiTimeframeStrategy(BaseStrategy):
    """Multi-timeframe pullback-to-trend strategy.

    Uses an internally aggregated higher-timeframe (default 5m) trend gate
    and looks for entries on the 1m timeframe when price pulls back near
    SMA_20 with neutral RSI — i.e. trades retracements *within* an uptrend
    rather than catching a falling knife.

    Entry conditions (long):
    - Higher-timeframe trend is UP (price > HTF SMA)
    - 1m regime is not TRENDING_DOWN
    - 1m close within ``pullback_pct`` of SMA_20 (pullback to support)
    - 1m RSI in the neutral band ``[rsi_min, rsi_max]``
    - Strategy not at its per-strategy max_positions cap

    Exit conditions:
    - Higher-timeframe trend flips DOWN
    - Take profit (default 3%)
    - Stop loss (default 2%)
    """

    def __init__(self, strategy_id: str, config: dict):
        super().__init__(strategy_id, config)

        self.trend_period = config.get("trend_period", 20)
        self.trend_interval_minutes = config.get("trend_interval_minutes", 5)

        self.pullback_pct = config.get("pullback_pct", 0.003)
        self.rsi_min = config.get("rsi_min", 40)
        self.rsi_max = config.get("rsi_max", 60)

        self.stop_loss_pct = config.get("stop_loss_pct", 0.02)
        self.take_profit_pct = config.get("take_profit_pct", 0.03)
        self.position_size = Decimal(str(config.get("position_size", 100)))

        syms = config.get("allowed_symbols")
        self.allowed_symbols: Optional[set[str]] = set(syms) if syms else None

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

        if symbol not in self._current_htf_candle:
            self._current_htf_candle[symbol] = {
                "start_minute": (minute // interval) * interval,
                "close": close,
            }

        current = self._current_htf_candle[symbol]
        expected_start = (minute // interval) * interval

        if expected_start != current["start_minute"]:
            if symbol not in self._trend_closes:
                self._trend_closes[symbol] = []
            self._trend_closes[symbol].append(current["close"])

            max_size = self.trend_period * 2
            if len(self._trend_closes[symbol]) > max_size:
                self._trend_closes[symbol] = self._trend_closes[symbol][-max_size:]

            self._current_htf_candle[symbol] = {
                "start_minute": expected_start,
                "close": close,
            }
        else:
            current["close"] = close

    def _get_trend(self, symbol: str) -> str | None:
        """Determine trend from higher timeframe data.

        Returns:
            'up', 'down', or None if insufficient data
        """
        closes = self._trend_closes.get(symbol, [])
        if len(closes) < self.trend_period:
            return None

        recent = closes[-self.trend_period:]
        sma = sum(recent) / len(recent)
        current = closes[-1]

        return "up" if current > sma else "down"

    def on_bar(self, data: BarWithIndicators) -> Optional[Order]:
        if self.allowed_symbols is not None and data.symbol not in self.allowed_symbols:
            return None

        symbol = data.symbol
        price = float(data.close)
        bar_time = data.bar.timestamp

        self._aggregate_to_htf(symbol, bar_time, price)

        trend = self._get_trend(symbol)
        if trend is None:
            return None

        position = self.get_position(symbol)

        if position and position.quantity > 0:
            return self._check_exit(data, position, trend)

        return self._check_entry(data, trend)

    def _check_entry(self, data: BarWithIndicators, trend: str) -> Optional[Order]:
        if self.at_capacity():
            return None
        if trend != "up":
            return None
        if data.regime == MarketRegime.TRENDING_DOWN:
            return None
        if data.rsi_14 is None or data.sma_20 is None:
            return None
        if not (self.rsi_min <= data.rsi_14 <= self.rsi_max):
            return None
        if data.sma_20 == 0:
            return None
        if abs(data.close - data.sma_20) / data.sma_20 > self.pullback_pct:
            return None

        return Order(
            strategy_id=self.strategy_id,
            symbol=data.symbol,
            side=OrderSide.BUY,
            quantity=self.position_size,
            order_type=OrderType.MARKET,
        )

    def _check_exit(
        self, data: BarWithIndicators, position, trend: str
    ) -> Optional[Order]:
        price = float(data.close)

        if trend == "down":
            return self._create_close_order(data.symbol, position.quantity)

        if position.avg_entry_price:
            entry_price = float(position.avg_entry_price)
            pnl_pct = (price - entry_price) / entry_price

            if pnl_pct >= self.take_profit_pct:
                return self._create_close_order(data.symbol, position.quantity)

            if pnl_pct <= -self.stop_loss_pct:
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
