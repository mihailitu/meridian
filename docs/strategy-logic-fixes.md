# Strategy Logic Fixes

> Working doc for the strategy-logic rewrite (now on `main`), the OMS re-entry bug fix, and the OOS validation that followed.
> Broader architectural issues live in [`AUDIT-2026-05-02.md`](AUDIT-2026-05-02.md). Project-level priorities live in [`../ROADMAP.md`](../ROADMAP.md). Phased execution plan lives in [`active-plan.md`](active-plan.md). This file stays scoped to strategy logic.

## Context

Fulltest baseline (2025-08-01 to 2026-02-01, 5 symbols + discovery, $100K) returned **-0.94%** with **30.7% win rate** (`fulltest_20260218_221730`). Only `mean_reversion` (40% WR, 0.61 PF) was modestly OK. `multi_timeframe` posted 14.3% WR and 0.09 PF; `pairs` fired one trade in 6 months; `momentum` posted zero trades because nothing satisfied the contradictory `RSI<40 AND price>SMA_20` condition for the symbols in scope.

Root causes from the audit: contradictory entry logic, unused regime/volatility data from indicators, tight stops, and a 93% order rejection rate from risk limits.

## Post-OMS-fix + OOS findings (2026-05-12)

**Stop using the Phase 2 / Phase 2.6 per-strategy numbers below as ground truth.** The OMS re-entry bug (Phase 2.7, commit `08c9224`) hid the real per-strategy P&L behind ghost positions for any strategy that closed and re-entered the same symbol. With the bug fixed and proper IS/OOS validation (Phase 2.8, commit `8ed17f1`) on the full historical window, every strategy's real story changed:

**Baseline (`data/fulltest_results/oos_comparison_20260512_211515.txt`)** — IS year 2024-08→2025-08 vs OOS half-year 2025-08→2026-02, AAPL/MSFT/GOOGL/AMZN/NVDA + discovery on, `multi_timeframe` / `mean_reversion` / `momentum` narrowed to the 5 gateway symbols:

| Strategy | IS Trades | IS WR | IS PF | IS P&L | OOS Trades | OOS WR | OOS PF | OOS P&L | Verdict |
|----------|----------:|------:|------:|-------:|-----------:|-------:|-------:|--------:|---------|
| `discovery_momentum` | 69 | 4.3% | 0.04 | -$148 | 485 | 33.4% | 0.56 | -$1,975 | IS_UNPROFITABLE — but IS sample asymmetric, worth a diagnosis pass |
| `mean_reversion` | 78 | 52.6% | **1.29** | **+$714** | 29 | 27.6% | 0.27 | -$606 | **BROKEN** — IS edge does not generalize |
| `multi_timeframe` | 613 | 14.5% | 0.24 | -$10,773 | 294 | 13.9% | 0.28 | -$5,159 | IS_UNPROFITABLE — signal has no edge |
| `pairs` | 7 | 0% | 0.00 | -$253 | 3 | 33.3% | 0.01 | -$235 | IS_UNPROFITABLE — too low-frequency |

**Honest read:**

1. **`multi_timeframe`** lost ~$11K IS on 613 trades, 14% WR. The pullback-to-trend signal is not catching pullbacks; it's catching peaks that fall. A 2% stop / 3% take-profit on a 14% WR is mathematically a losing strategy regardless of tuning. **Not a tuning problem — a signal problem.**
2. **`mean_reversion`** is the only strategy that passed IS (PF 1.29, +$714 on 78 trades). The OOS collapse to PF 0.27 / -$606 is the canonical in-sample overfit signature. Worth understanding what made IS profitable (regime mix? specific symbols? specific 2024 events?) before concluding the strategy is dead — but the OOS evidence strongly suggests the IS edge was period-specific.
3. **`discovery_momentum`**'s asymmetry is the most interesting finding: IS PF 0.04 (catastrophic, 69 trades) but OOS PF 0.56 (485 trades). Too lopsided to be sample variance. Three likely causes: (a) scoring bug specific to the 2024-08→2025-08 window, (b) discovery feed composition drifts sharply between periods so the strategy was trading systematically worse symbols IS, (c) real but regime-dependent edge. Priority diagnostic — this is the only strategy that ever showed positive expectancy in any test.
4. **`pairs`** is structurally low-frequency. 7 IS trades over 12 months on AAPL/MSFT can't meaningfully be evaluated. If kept, retune to a wider pair set or accept it as a low-priority experiment.

**Conclusion**: parameter tuning won't lift any of these from PF 0.17–0.30 to PF >1.0. The signals don't have edge. Three paths forward are laid out in [`active-plan.md`](active-plan.md) Phase 3 (diagnose discovery_momentum / replace with research-backed signal / reframe as platform project).

## Followup tuning items — SUPERSEDED by Post-OMS-fix findings above

The four items below were generated before the OMS bug was found and before OOS validation existed. They are kept as historical record; **don't act on them**. Each item's conclusion was based on bug-masked per-strategy numbers (see Phase 2.7 in `active-plan.md` for the AMZN ghost-pyramid example that made the 0/10 multi_timeframe WR misleading).

1. ~~**Mean reversion exit** — APPLIED + KEPT 2026-05-10~~. Outcome is now subsumed by the IS/OOS verdict above: PF 1.29 IS → 0.27 OOS confirms the strategy doesn't generalize regardless of the exit choice.
2. ~~**Momentum entry gate** — TRIED + REVERTED 2026-05-10~~. With universe narrowing live, momentum no longer competes with `discovery_momentum` on the discovered universe. Whether to re-enable momentum is gated on Phase 3 direction.
3. ~~**Multi-timeframe re-entry cooldown** — DEFERRED~~. 613 IS / 294 OOS trades suggest re-entry isn't the bottleneck; signal quality is.
4. ~~**Pairs follow-through** — DEFERRED~~. Still deferred and no longer in the top-of-mind list.

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
