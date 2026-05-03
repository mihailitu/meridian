# TODO: Improve Fulltest Win Performance

> Broader architectural issues live in [`docs/AUDIT-2026-05-02.md`](docs/AUDIT-2026-05-02.md). This file stays scoped to strategy logic.

## Context

Fulltest baseline (2025-08-01 to 2026-02-01, 5 symbols + discovery, $100K) returned **-0.94%** with **30.7% win rate** (`fulltest_20260218_221730`). Only `mean_reversion` (40% WR, 0.61 PF) was modestly OK. `multi_timeframe` posted 14.3% WR and 0.09 PF; `pairs` fired one trade in 6 months; `momentum` posted zero trades because nothing satisfied the contradictory `RSI<40 AND price>SMA_20` condition for the symbols in scope.

Root causes from the audit: contradictory entry logic, unused regime/volatility data from indicators, tight stops, and a 93% order rejection rate from risk limits.

## Status — 2026-05-03

Items §1–§4, §6 and §7 are **done** on branch `strategy-logic-fixes`. §5 (Sharpe) remains deferred per its original text. Validation against the full baseline is **incomplete** — see "Open issues" below.

### 1. Momentum — DONE (`strategies/momentum.py`)
**Was**: `RSI < 40 AND price > SMA_20` (contradictory; rarely triggers; 6.8% WR / 0 trades depending on universe).

**Now**: regime-aware breakout —
- Regime in `TRENDING_UP` or `BREAKOUT`
- `trend_strength > 30`
- RSI **crossing up** through 50 (prev ≤ 50 < current) — tracked per symbol
- Close > SMA_20
- Trailing exit if regime flips to `TRENDING_DOWN`
- Stop loss widened 2% → 3%

### 2. Multi-Timeframe — DONE (`strategies/multi_timeframe.py`)
**Was**: 5m UP + 1m RSI < 40 (oversold-in-uptrend trap; 11.3–14.3% WR).

**Now**: pullback-to-trend —
- HTF (5m) trend up
- 1m close within 0.3% of SMA_20 (pullback to support)
- 1m RSI in `[40, 60]` (neutral, not deeply oversold)
- Skip when 1m regime is `TRENDING_DOWN`
- Stop 1.5% → 2%, take-profit 3% (unchanged)

### 3. Mean Reversion — DONE (`strategies/mean_reversion.py`)
**Was**: enter at lower band + RSI<35, exit at upper band, stop 2%.

**Now**:
- Entry gated on regime ∈ `RANGING_QUIET` / `RANGING_VOLATILE`
- **Exit at middle band (SMA)** instead of upper band — captures reliable reversion, not full swing
- Stop 2% → 1.5%
- RSI > 70 still acts as secondary exit

### 4. Pairs — DONE (`strategies/pairs.py`)
Defaults retuned: `lookback` 20 → 60, `entry_zscore` 2.0 → 1.5, `exit_zscore` 0.5 → 0.3. Strategy structure unchanged.

### 5. Sharpe Ratio — STILL DEFERRED
Needs mark-to-market equity (bar prices for open positions during analytics). Not in scope for this branch.

### 6. Fulltest `max_positions` — DONE (commit `94042bb`, before this branch)
Orchestrator overrides `oms.max_positions` to 50; live config stays at 20.

### 7. Per-strategy `max_positions` — DONE (commit `94042bb`)
`BaseStrategy.at_capacity()` now exists and is checked by all four rewritten strategies before emitting an entry.

## Cross-cutting changes

All four rewritten strategies now call `self.at_capacity()` before emitting entries, so they self-limit before the OMS rejects them. This dropped wasted-order noise during the partial fulltest run.

## Open issues from the partial fulltest run (killed at 57min)

A full apples-to-apples comparison against the baseline did not complete — the run was killed before report generation. Mid-run snapshot from the DB at ~57min:

| Strategy | Fills (incomplete) | Note |
|---|---:|---|
| `multi_timeframe-bt` | 692 | very chatty — pullback band 0.3% may be too loose, or needs a re-entry cooldown after exit |
| `discovery_momentum-bt` | 237 | reasonable |
| `mean_reversion-bt` | 251 | reasonable; up from 55 in baseline |
| `pairs-bt` | 3 | up from 1; capped at 1 position by design |
| `momentum-bt` | 0 | regime + trend_strength gate too strict on 1m bars; the combined condition rarely fires |

Total mid-run fills: 1,186 (vs 88 in baseline) — strategies are firing far more, win rates not measured. Order count was ~42K; OMS rejected most before fill.

### Followups suggested by the partial run

1. **Momentum entry gate is too strict.** `TRENDING_UP`/`BREAKOUT` + `trend_strength > 30` + RSI crossing 50 + price > SMA combined produce zero entries on the 5 named symbols over 6 months. Likely fixes: relax `trend_strength_min` to 15–20, allow `RANGING_QUIET` as a valid regime when trend_strength is high, or weaken the cross to "RSI > 50 AND prev <= 50 within last N bars".
2. **Multi-timeframe re-entry cooldown.** 692 fills suggests the same symbol is being re-entered immediately after exit. Add a per-symbol minimum bar-count gap before a new entry.
3. **Aggregator persistence is the throughput bottleneck for fulltest** (see audit addendum). At ~50 bars/sec single-row INSERT, a 6-month / 5-symbol replay + S&P discovery takes 60–90+ minutes — 2× the prior baseline since BB/ATR were added. Worth batching or COPY-buffering before more fulltest iterations.

## Verification

Unit tests: 870 collected, 866 strategy-related pass. The 4 failures (`test_alerts.py` event-loop fixtures, `test_oms_broker.py::test_submit_order_requires_price`) pre-exist on `main` and are unrelated.

```bash
.venv/bin/pytest
```

For fulltest comparison, historical parquets are in `data/historical/` (no download needed). Run the same parameters as the baseline:

```bash
python -m axtrade.fulltest run --start 2025-08-01 --end 2026-02-01 \
  --symbols AAPL MSFT GOOGL AMZN NVDA --capital 100000
```

Compare against `data/fulltest_results/fulltest_20260218_221730.txt`. Target metrics from the original plan:
- Overall win rate: 30.7% → 35%+
- Mean reversion profit factor: 0.61 → higher
- Pairs: more than 1 trade
- discovery_momentum: remain profitable (regression check)

Plan to revisit the open issues above before publishing a comparison report.
