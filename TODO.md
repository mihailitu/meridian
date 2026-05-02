# TODO: Improve Fulltest Win Performance

> Broader architectural issues (Sharpe bug, indicator→strategy wiring, IBKR `add_symbols` no-op, design-doc drift) live in [`docs/AUDIT-2026-05-02.md`](docs/AUDIT-2026-05-02.md). This file stays scoped to strategy logic.

## Context

Fulltest (2025-08-01 to 2026-02-01, 5 symbols + discovery, $100K) returned **-1.53%** with a **23.8% win rate**. Only `discovery_momentum` was profitable (+$248, 47% WR, 1.80 PF). The other strategies are deeply negative — `momentum` at 6.8% WR and `multi_timeframe` at 11.3% WR are worse than random. Root causes: contradictory entry logic, unused regime/volatility data from indicators, tight stops, and a 93% order rejection rate from risk limits.

## Changes

### 1. Fix Momentum Strategy — entry logic is self-contradictory
**File**: `src/axtrade/strategies/momentum.py`

**Problem**: Buys when RSI < 40 (selling pressure) AND price > SMA_20 (uptrend). These rarely co-occur on 1m bars, and when they do the move is already exhausted. 6.8% win rate (3W/41L).

**Fix**:
- Change entry to **momentum breakout**: RSI crossing above 50 (building strength) AND price > SMA_20 AND `regime` is `TRENDING_UP` or `BREAKOUT`
- Use `trend_strength` (available in `BarWithIndicators` but currently unused) — require `trend_strength > 30`
- Widen stop loss from 2% to **3%** (matches discovery_momentum's successful 3%)
- Add trailing exit: if `regime` shifts to `TRENDING_DOWN`, close position
- Keep RSI > 70 overbought exit

### 2. Fix Multi-Timeframe Strategy — same oversold-in-uptrend trap
**File**: `src/axtrade/strategies/multi_timeframe.py`

**Problem**: Entry requires 5m trend UP + 1m RSI < 40 (oversold). Same contradictory timing. 11.3% win rate (6W/47L).

**Fix**:
- Change entry to **pullback-to-trend**: 5m trend UP + price dips to within 0.3% of SMA_20 (pullback to support) + RSI between 40-60 (neutral, not deeply oversold)
- Widen stop loss from 1.5% to **2%**
- Keep take profit at 3% (currently 2:1 R:R in theory, fixing entry timing makes it achievable)
- Use `regime` as additional filter — skip entries when `TRENDING_DOWN`

### 3. Fix Mean Reversion Strategy — winners too small, losers too large
**File**: `src/axtrade/strategies/mean_reversion.py`

**Problem**: 43% win rate is decent but avg winner ($22) < avg loser ($31). Exits at upper Bollinger Band are too ambitious. Enters in downtrends where mean reversion fails.

**Fix**:
- Exit target: **middle band** (SMA) instead of upper band — captures reliable reversion, not full swing
- Add regime filter: only enter when `regime` is `RANGING` — skip when `TRENDING_DOWN` (biggest loser scenario)
- Reduce stop loss from 2% to **1.5%** — combined with faster profit target, cuts loss magnitude while maintaining win rate
- Keep RSI > 70 overbought exit as secondary

### 4. Fix Pairs Strategy — entry threshold too conservative
**File**: `src/axtrade/strategies/pairs.py`

**Problem**: z-score entry threshold of 2.0 (a ~2.5% probability event) produced only 1 trade in 6 months. Lookback of 20 bars (20 minutes on 1m data) is far too short for ratio statistics.

**Fix**:
- Lower `entry_zscore` from 2.0 to **1.5**
- Increase `lookback` from 20 to **60** (1 hour of 1m data — more statistically meaningful)
- Widen `exit_zscore` from 0.5 to **0.3** (let winning trades run closer to mean)

### 5. Fix Sharpe Ratio — always reports 0.00
**File**: `src/axtrade/fulltest/analytics.py`

**Problem**: The equity curve in `_process_fills` uses cost-basis accounting (`cash + open_position_cost`). Between fills, equity is flat. After daily resampling, most returns are 0.0, making the Sharpe denominator overwhelm the numerator and round to 0.00.

**Fix**:
This is a deeper change — skip for now. The Sharpe needs mark-to-market equity (tracking unrealized P&L using market prices), which requires bar price data during analytics. Add a TODO comment noting the limitation. The other metrics (profit factor, win rate, drawdown) are reliable and more actionable.

### 6. Raise Fulltest Max Positions — 93% order rejection rate
**File**: `src/axtrade/fulltest/orchestrator.py`

**Problem**: Global `max_positions=20` is shared across all strategies. With 4-5 strategies trading 50+ discovered symbols, the cap is hit immediately. 25,157 orders produced only 1,832 fills (7.3%).

**Fix**:
- In the fulltest orchestrator's `_build_config`, override `config.oms.max_positions` to **50** (5 strategies × 10 positions each)
- This only affects fulltest — live config stays at 20

### 7. Add Per-Strategy Position Limits to Base Class
**File**: `src/axtrade/strategies/base.py`

**Problem**: Only `discovery_momentum` has its own `max_positions` check (10). Other strategies generate unlimited signals that get rejected at the OMS level — wasteful and noisy.

**Fix**:
- Add optional `max_positions` parameter to `BaseStrategy.__init__` (default: `None` = unlimited)
- Add `_at_capacity()` helper that checks `len(self.positions) >= max_positions`
- Set `max_positions=10` in momentum, mean_reversion, multi_timeframe configs via orchestrator
- Pairs already limited to 1 position by design

## Files Modified

1. `src/axtrade/strategies/momentum.py` — new entry/exit logic using regime + trend_strength
2. `src/axtrade/strategies/multi_timeframe.py` — pullback-to-trend entry instead of oversold
3. `src/axtrade/strategies/mean_reversion.py` — middle band exit, regime filter, tighter stop
4. `src/axtrade/strategies/pairs.py` — looser z-score threshold, longer lookback
5. `src/axtrade/strategies/base.py` — add `max_positions` support
6. `src/axtrade/fulltest/orchestrator.py` — raise max_positions to 50, pass per-strategy max_positions config
7. `src/axtrade/fulltest/analytics.py` — add TODO comment on Sharpe limitation

## Verification

1. Run unit tests: `make test`
2. Run fulltest with same parameters:
   ```bash
   python -m axtrade.fulltest --start 2025-08-01 --end 2026-02-01 --symbols AAPL MSFT GOOGL AMZN NVDA --capital 100000
   ```
3. Compare results against baseline (the current fulltest_20260217_062342):
   - Overall win rate should improve from 23.8% toward 35%+
   - Momentum win rate should improve from 6.8% significantly
   - Multi_timeframe win rate should improve from 11.3%
   - Mean reversion profit factor should improve from 0.53
   - Pairs should generate more than 1 trade
   - Total fill rate should improve from 7.3%
   - discovery_momentum should remain profitable (regression check)
