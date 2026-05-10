# Strategy Logic Fixes

> Working doc for the strategy-logic rewrite (now on `main`) and the followups it surfaced.
> Broader architectural issues live in [`AUDIT-2026-05-02.md`](AUDIT-2026-05-02.md). Project-level priorities live in [`../ROADMAP.md`](../ROADMAP.md). Phased execution plan lives in [`active-plan.md`](active-plan.md). This file stays scoped to strategy logic.

## Context

Fulltest baseline (2025-08-01 to 2026-02-01, 5 symbols + discovery, $100K) returned **-0.94%** with **30.7% win rate** (`fulltest_20260218_221730`). Only `mean_reversion` (40% WR, 0.61 PF) was modestly OK. `multi_timeframe` posted 14.3% WR and 0.09 PF; `pairs` fired one trade in 6 months; `momentum` posted zero trades because nothing satisfied the contradictory `RSI<40 AND price>SMA_20` condition for the symbols in scope.

Root causes from the audit: contradictory entry logic, unused regime/volatility data from indicators, tight stops, and a 93% order rejection rate from risk limits.

## Followup tuning items

Surfaced by the partial fulltest run + the post-rewrite validation.

1. **Mean reversion exit** — APPLIED + KEPT 2026-05-10. Reverted middle-band exit back to upper-band exit. Validation had shown avg winner shrank $41 → $16 with middle-band while avg loser only shrank $-45 → $-17, so PF dropped from 0.61 → 0.35. **Phase 2 result with upper-band restored**: PF 0.35 → 0.59, avg winner $16 → $35, WR 27.5% → 33.3%. Still net-loss but trajectory is right.
2. **Momentum entry gate** — TRIED + REVERTED 2026-05-10. Lowered `trend_strength_min` 30 → 20 and widened the RSI cross window from 1 → 5 bars. This enabled trades (0 → 6 over 6 months) but they net-lost $135. Strategy was trading exclusively on discovery-fed names (TAP, TRGP, CL, CRL, IDXX, FOX), competing with `discovery_momentum` (52.9% WR, +$264) on the same opportunities with worse logic. Tightening the stop from 3% → 2% changed nothing — losses don't exit via stop, they exit via regime-flip / RSI. Conclusion: momentum needs deeper rework (exit asymmetry — winners exit early on regime/RSI while losers run wider). Reverted to validation defaults; revisit once other phases land.
3. **Multi-timeframe re-entry cooldown** — DEFERRED. Validation showed 53 trades over 6 months (down from the 692-fills partial-run snapshot once `at_capacity()` lands), so the original whipsaw concern is no longer urgent. Re-evaluate if a future run shows excess fills.
4. **Pairs follow-through** — DEFERRED. Validation: 1 trade, 0 wins. Strategy is structurally low-frequency. Don't tune further until other strategies post positive expectancy.

## Status — 2026-05-10

Items §1–§4, §6 and §7 below are **merged to `main`** (commits `27063ed`, `e60dc84`, `b5fe036`, `94042bb`). §5 (Sharpe) is deferred to Phase 3 of [`active-plan.md`](active-plan.md). **Validation complete** — see "Validation results" below.

## Validation results

Two reference runs, same params (5 symbols + discovery, $100K, 2025-08 → 2026-02):

- **Post-rewrite, pre-PR** (`fulltest_20260510_105510.txt`): +0.05% / 29.5% WR / 0.91 PF / 122 trades. Mean reversion regressed to PF 0.35.
- **Post-PR canonical** (`fulltest_20260510_210714.txt`): **+0.06% / 31.97% WR / 0.93 PF / 122 trades**. Mean reversion fix landed; +$11 net.

| Strategy | Trades | WR | PF | P&L | Note |
|---|---:|---:|---:|---:|---|
| `discovery_momentum` | 17 | 52.9% | 1.63 | +$265 | working as intended |
| `multi_timeframe` | 53 | 24.5% | 1.17 | +$295 | working as intended |
| `mean_reversion` | 51 | 33.3% | 0.59 | -$306 | upper-band exit lifted PF 0.35→0.59 (avg winner $16→$35); still net-loss |
| `pairs` | 1 | 0% | 0.00 | -$196 | structurally low-frequency by design |
| `momentum` | 0 | — | — | — | gate too strict on baseline 5 symbols; relaxation tried+reverted (see followups §2) |

Compared to the pre-rewrite 480-symbol baseline (`fulltest_20260218_221730.txt`, -0.94%): not strictly apples-to-apples (different symbol set + 1 vs 3850 discovery scans), but the rewrites + PR moved net P&L from -$935 → +$57.

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

**Now** (after PR `validation-and-improvements` on 2026-05-10):
- Entry gated on regime ∈ `RANGING_QUIET` / `RANGING_VOLATILE`
- Exit at upper Bollinger Band (full mean-reversion swing)
- Stop 2% → 1.5%
- RSI > 70 still acts as secondary exit

Middle-band exit was tried first but reverted: it shrank avg winner $41→$16 while avg loser only shrank $-45→$-17, dropping PF from 0.61 to 0.35. Restoring upper-band exit on the RANGING-only gate recovered PF to 0.59.

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

## Mid-run snapshot from the partial fulltest

The original validation was killed at 57min before report generation. DB snapshot at that point:

| Strategy | Fills (incomplete) | Note |
|---|---:|---|
| `multi_timeframe-bt` | 692 | very chatty — re-entry whipsaw, see followup §2 |
| `discovery_momentum-bt` | 237 | reasonable |
| `mean_reversion-bt` | 251 | reasonable; up from 55 in baseline |
| `pairs-bt` | 3 | up from 1; capped at 1 position by design |
| `momentum-bt` | 0 | regime + trend_strength gate too strict, see followup §1 |

Total mid-run fills: 1,186 (vs 88 in baseline) — strategies are firing far more, win rates not measured. Order count was ~42K; OMS rejected most before fill.

## Verification

Unit tests: 870 collected, 866 strategy-related pass. The 4 failures (`test_alerts.py` event-loop fixtures, `test_oms_broker.py::test_submit_order_requires_price`) pre-exist on `main` and are unrelated.

```bash
.venv/bin/pytest
```

The validation fulltest is the regression baseline going forward. Historical parquets are in `data/historical/` (no download needed):

```bash
python -m axtrade.fulltest run --start 2025-08-01 --end 2026-02-01 \
  --symbols AAPL MSFT GOOGL AMZN NVDA --capital 100000
```

Compare against `data/fulltest_results/fulltest_20260218_221730.txt`. Target metrics:
- Overall win rate: 30.7% → 35%+
- Mean reversion profit factor: 0.61 → higher
- Pairs: more than 1 trade
- discovery_momentum: remain profitable (regression check)
