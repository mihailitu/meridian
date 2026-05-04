# Iteration 7: Additional Strategies

## Goal
Expand the strategy library with different trading approaches: mean reversion, multi-timeframe confirmation, and pairs trading.

## Definition of Done
```bash
# All strategies available and tested
python -m axtrade.cli backtest mean_reversion --symbol AAPL --start 2024-01-01 --end 2024-01-31
python -m axtrade.cli backtest multi_timeframe --symbol AAPL --start 2024-01-01 --end 2024-01-31

# Config enables multiple strategies
strategies:
  enabled:
    - type: momentum
      id: momentum_01
    - type: mean_reversion
      id: mean_rev_01
    - type: multi_timeframe
      id: mtf_01
```

## New Strategies

### 1. Mean Reversion Strategy (Bollinger Bands)
**Logic**: Buy when price touches lower band (oversold), sell when touches upper band (overbought).

**Indicators needed**:
- Bollinger Bands (20-period SMA with 2 std dev bands)
- Already have SMA-20, need to add standard deviation calculation

**Entry/Exit**:
- BUY: Price <= Lower Band AND RSI < 35
- SELL: Price >= Upper Band OR RSI > 70 OR stop-loss hit

### 2. Multi-Timeframe Strategy
**Logic**: Use higher timeframe for trend direction, lower timeframe for entry timing.

**Approach**:
- 5m bars for trend (SMA-20 slope)
- 1m bars for entry signals
- Only take trades in direction of higher timeframe trend

**Entry/Exit**:
- BUY: 5m trend UP (price > SMA) AND 1m RSI oversold
- SELL: 5m trend DOWN OR stop-loss/take-profit

### 3. Pairs Trading Strategy (Simplified)
**Logic**: Trade mean reversion of price ratio between correlated symbols.

**Approach**:
- Track ratio of two symbols (e.g., AAPL/MSFT)
- Calculate z-score of ratio vs moving average
- Trade when z-score exceeds threshold

**Entry/Exit**:
- LONG spread: z-score < -2 (ratio too low, buy A, sell B)
- SHORT spread: z-score > 2 (ratio too high, sell A, buy B)
- Exit: z-score returns to 0

## Files to Create/Modify

### New Files
```
src/axtrade/indicators/bollinger.py     # Bollinger Bands calculation
src/axtrade/strategies/mean_reversion.py
src/axtrade/strategies/multi_timeframe.py
src/axtrade/strategies/pairs.py
tests/unit/test_bollinger.py
tests/unit/test_strategies_extended.py
```

### Modify Existing
```
src/axtrade/indicators/__init__.py      # Export Bollinger
src/axtrade/indicators/engine.py        # Add Bollinger to engine
src/axtrade/strategies/__init__.py      # Register new strategies
src/axtrade/strategies/base.py          # Add multi-symbol support
config/default.yaml                      # Add example configs
```

## Implementation Details

### 1. Bollinger Bands (indicators/bollinger.py)
```python
def calculate_bollinger_bands(
    prices: list[float],
    period: int = 20,
    num_std: float = 2.0
) -> tuple[float, float, float] | None:
    """Calculate Bollinger Bands.

    Returns:
        (middle, upper, lower) band values or None if insufficient data
    """
    if len(prices) < period:
        return None

    window = prices[-period:]
    middle = sum(window) / period
    std_dev = (sum((p - middle) ** 2 for p in window) / period) ** 0.5

    return (middle, middle + num_std * std_dev, middle - num_std * std_dev)
```

### 2. Mean Reversion Strategy
```python
class MeanReversionStrategy(BaseStrategy):
    """Mean reversion using Bollinger Bands."""

    def __init__(self, strategy_id: str, config: dict):
        super().__init__(strategy_id, config)
        self.bb_period = config.get("bb_period", 20)
        self.bb_std = config.get("bb_std", 2.0)
        self.rsi_oversold = config.get("rsi_oversold", 35)
        self.rsi_overbought = config.get("rsi_overbought", 70)
        self.stop_loss_pct = config.get("stop_loss_pct", 0.02)
        self.position_size = config.get("position_size", 100)

        self._price_buffer: dict[str, list[float]] = {}

    @property
    def name(self) -> str:
        return "MeanReversion"

    def on_bar(self, data: BarWithIndicators) -> Order | None:
        # Update price buffer
        symbol = data.symbol
        if symbol not in self._price_buffer:
            self._price_buffer[symbol] = []
        self._price_buffer[symbol].append(float(data.close))

        # Keep only needed history
        if len(self._price_buffer[symbol]) > self.bb_period:
            self._price_buffer[symbol] = self._price_buffer[symbol][-self.bb_period:]

        # Calculate Bollinger Bands
        bb = calculate_bollinger_bands(
            self._price_buffer[symbol],
            self.bb_period,
            self.bb_std
        )
        if bb is None or data.rsi_14 is None:
            return None

        middle, upper, lower = bb
        price = float(data.close)
        position = self._positions.get(symbol)

        # Entry: price at lower band + RSI oversold
        if position is None:
            if price <= lower and data.rsi_14 < self.rsi_oversold:
                return self._create_buy_order(symbol)

        # Exit: price at upper band, RSI overbought, or stop-loss
        else:
            entry_price = float(position.avg_entry_price)
            stop_price = entry_price * (1 - self.stop_loss_pct)

            if (price >= upper or
                data.rsi_14 > self.rsi_overbought or
                price <= stop_price):
                return self._create_sell_order(symbol, position.quantity)

        return None
```

### 3. Multi-Timeframe Strategy
```python
class MultiTimeframeStrategy(BaseStrategy):
    """Multi-timeframe trend following."""

    def __init__(self, strategy_id: str, config: dict):
        super().__init__(strategy_id, config)
        self.trend_period = config.get("trend_period", 20)  # For 5m trend
        self.rsi_oversold = config.get("rsi_oversold", 40)
        self.rsi_overbought = config.get("rsi_overbought", 60)
        self.stop_loss_pct = config.get("stop_loss_pct", 0.015)
        self.take_profit_pct = config.get("take_profit_pct", 0.03)
        self.position_size = config.get("position_size", 100)

        # Store 5m bar data for trend
        self._trend_prices: dict[str, list[float]] = {}
        self._last_5m_bar: dict[str, datetime] = {}

    @property
    def name(self) -> str:
        return "MultiTimeframe"

    def _get_trend(self, symbol: str) -> str | None:
        """Determine trend from 5m data: 'up', 'down', or None."""
        prices = self._trend_prices.get(symbol, [])
        if len(prices) < self.trend_period:
            return None

        sma = sum(prices[-self.trend_period:]) / self.trend_period
        current = prices[-1]

        return "up" if current > sma else "down"

    def on_bar(self, data: BarWithIndicators) -> Order | None:
        symbol = data.symbol

        # Aggregate to 5m bars for trend
        bar_time = data.bar.timestamp
        minute = bar_time.minute

        # Every 5 minutes, record close for trend
        if minute % 5 == 4:  # End of 5m period
            if symbol not in self._trend_prices:
                self._trend_prices[symbol] = []
            self._trend_prices[symbol].append(float(data.close))
            if len(self._trend_prices[symbol]) > self.trend_period * 2:
                self._trend_prices[symbol] = self._trend_prices[symbol][-self.trend_period * 2:]

        trend = self._get_trend(symbol)
        if trend is None or data.rsi_14 is None:
            return None

        position = self._positions.get(symbol)
        price = float(data.close)

        # Entry: trend up + RSI oversold on 1m
        if position is None:
            if trend == "up" and data.rsi_14 < self.rsi_oversold:
                return self._create_buy_order(symbol)

        # Exit: trend reversal, take-profit, or stop-loss
        else:
            entry_price = float(position.avg_entry_price)
            stop_price = entry_price * (1 - self.stop_loss_pct)
            target_price = entry_price * (1 + self.take_profit_pct)

            if (trend == "down" or
                price >= target_price or
                price <= stop_price):
                return self._create_sell_order(symbol, position.quantity)

        return None
```

### 4. Pairs Trading Strategy
```python
class PairsStrategy(BaseStrategy):
    """Pairs trading on correlated symbols."""

    def __init__(self, strategy_id: str, config: dict):
        super().__init__(strategy_id, config)
        self.symbol_a = config.get("symbol_a", "AAPL")
        self.symbol_b = config.get("symbol_b", "MSFT")
        self.lookback = config.get("lookback", 20)
        self.entry_zscore = config.get("entry_zscore", 2.0)
        self.exit_zscore = config.get("exit_zscore", 0.5)
        self.position_size = config.get("position_size", 50)

        self._prices_a: list[float] = []
        self._prices_b: list[float] = []
        self._spread_position: str | None = None  # "long" or "short"

    @property
    def name(self) -> str:
        return f"Pairs({self.symbol_a}/{self.symbol_b})"

    def _calculate_zscore(self) -> float | None:
        if len(self._prices_a) < self.lookback or len(self._prices_b) < self.lookback:
            return None

        # Calculate ratio
        ratios = [a / b for a, b in zip(self._prices_a[-self.lookback:],
                                         self._prices_b[-self.lookback:])]

        mean = sum(ratios) / len(ratios)
        std = (sum((r - mean) ** 2 for r in ratios) / len(ratios)) ** 0.5

        if std == 0:
            return None

        current_ratio = self._prices_a[-1] / self._prices_b[-1]
        return (current_ratio - mean) / std

    def on_bar(self, data: BarWithIndicators) -> Order | None:
        # Update price buffers
        symbol = data.symbol
        price = float(data.close)

        if symbol == self.symbol_a:
            self._prices_a.append(price)
            if len(self._prices_a) > self.lookback * 2:
                self._prices_a = self._prices_a[-self.lookback * 2:]
        elif symbol == self.symbol_b:
            self._prices_b.append(price)
            if len(self._prices_b) > self.lookback * 2:
                self._prices_b = self._prices_b[-self.lookback * 2:]
        else:
            return None

        zscore = self._calculate_zscore()
        if zscore is None:
            return None

        # Only generate orders for symbol_a (simplified - real pairs would trade both)
        if symbol != self.symbol_a:
            return None

        position = self._positions.get(self.symbol_a)

        # Entry signals
        if position is None and self._spread_position is None:
            if zscore < -self.entry_zscore:
                # Ratio too low, buy A (expect ratio to rise)
                self._spread_position = "long"
                return self._create_buy_order(self.symbol_a)
            elif zscore > self.entry_zscore:
                # Ratio too high, sell A (expect ratio to fall)
                # Note: simplified - only trading one leg
                pass

        # Exit signals
        elif position is not None and self._spread_position == "long":
            if abs(zscore) < self.exit_zscore:
                self._spread_position = None
                return self._create_sell_order(self.symbol_a, position.quantity)

        return None
```

## Implementation Order

1. **Bollinger Bands**: Create indicator calculation
2. **Mean Reversion**: Implement strategy using Bollinger + RSI
3. **Multi-Timeframe**: Implement with 5m trend + 1m entry
4. **Pairs Trading**: Implement z-score based pairs strategy
5. **Update Engine**: Add Bollinger to IndicatorEngine
6. **Register Strategies**: Add to STRATEGY_TYPES
7. **Tests**: Unit tests for all new code
8. **Config**: Add example configurations

## Verification Steps

1. Run tests: `pytest tests/unit/test_bollinger.py tests/unit/test_strategies_extended.py -v`
2. Backtest each strategy:
   ```bash
   python -m axtrade.cli backtest mean_reversion --symbol AAPL --start 2024-01-01 --end 2024-01-31
   python -m axtrade.cli backtest multi_timeframe --symbol AAPL --start 2024-01-01 --end 2024-01-31
   ```
3. Run all tests: `pytest -v`
