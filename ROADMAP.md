# Roadmap

> Where the project actually is, what's next, and what's deferred.
> For deeper detail on any item, follow the link to the audit or work doc.

_Last refreshed: 2026-05-10._

## Today

- **Pipeline works end-to-end** in paper / fulltest mode: gateway → aggregator (with SMA, RSI, BB, ATR, regime) → strategies → OMS → DB. Web UI shows positions, P&L, alerts.
- **Strategies don't have working edge yet.** Real (non-phantom) baseline after PaperBroker cash check landed: +0.09% return / 23.5% WR / 1.30 PF over 6 months on 5 symbols + S&P discovery (`data/fulltest_results/fulltest_20260511_062659.txt`). Only `discovery_momentum` shows actual edge (6 trades, 66.7% WR, +$270). `multi_timeframe` lost all 10 trades it managed to take (its prior +$295 was phantom-fill noise). `mean_reversion`, `pairs`, `momentum` traded 0-1 times. Total 17 closed round-trips in 6 months — strategies open positions on Aug 1, can't generate exit signals, sit on capital. The "+$57 from 122 trades" earlier baselines were largely fiction.
- **Strategy rewrites merged to `main`** (`27063ed`, `e60dc84`, `b5fe036`, `94042bb`) plus the `validation-and-improvements` PR (mean_reversion upper-band exit + drop `run_in_executor` + Phase 2.5 diagnostics + Phase 2.6 cash check). Detail: [`docs/strategy-logic-fixes.md`](docs/strategy-logic-fixes.md), [`docs/active-plan.md`](docs/active-plan.md).
- **Data inventory**: `data/historical/` holds 1,447 unique symbols across two periods (2024-08 → 2025-08 and 2025-08 → 2026-02), ~6.3 GB. Covers full S&P 1500 universe in both windows.
- **Active plan**: phased execution doc at [`docs/active-plan.md`](docs/active-plan.md).

## What's next (chop order)

In rough priority. Item codes (A1, B2, etc.) are the audit's IDs — see [`docs/AUDIT-2026-05-02.md`](docs/AUDIT-2026-05-02.md) for evidence and fix direction. Full phase detail in [`docs/active-plan.md`](docs/active-plan.md).

| # | Item | Why now | Status |
|---|------|---------|--------|
| 1 | **Strategy edge work — `multi_timeframe` (0/10 WR) and `mean_reversion` (1 trade)** | Phase 2.6 surfaced ground truth: rule-based strategies don't have working edge. `multi_timeframe`'s prior +$295 was phantom-fill noise; with real cash constraint, all 10 of its real trades lost. `mean_reversion` barely fires at all. Fixing entry/exit on these is the only path to making the platform actually useful | next up |
| 2 | Strategy turnover — strategies open positions on Aug 1 then sit on capital for 5.5 months | Related to #1. 8 positions stay open all 6 months, tying up ~$82K of $100K capital. Strategies need either time-based exits, smaller positions, or genuinely better signals to keep trading. Decide which before tuning | next up |
| 3 | B2: delete `ml/` (966 LoC of disabled hand-rolled GD) | Cheap simplification; stops "what's this for?" friction. ~2 hours, orthogonal | not started |
| 4 | Momentum redo | Current relaxed gate trades only on discovery-fed names where `discovery_momentum` already does it better | gated on #1 |
| 5 | Expand testing: 18-month window + S&P 1500 universe | Per user: tune on 6mo first, then expand. Data already on disk | gated on strategies actually showing edge |
| 6 | IBKR `add_symbols` (A3) + paper integration test (C2) | Gate before any live IBKR submission | gated on strategies posting positive expectancy |

**Per-strategy state (post-Phase 2.6, real fills only)**:
- `discovery_momentum`: 6 trades, **66.7% WR**, +$270.60, avg winner $65 / avg loser $-2 ✓ shows real edge
- `multi_timeframe`: 10 trades, **0% WR**, all 10 lost, -$150 — prior +$295 was phantom
- `mean_reversion`: 1 trade, lost $26 — barely fires under cash constraint
- `pairs`: 0 trades
- `momentum`: 0 trades

**Phase 2.5 + 2.6 deliverables** (PR `validation-and-improvements`): per-symbol P&L breakdown in every strategy's report section; portfolio Sharpe now meaningful when strategies trade enough; fills timestamped on simulated bar time (`PaperBroker.set_current_time`); PaperBroker cash check rejecting buys that would overdraw — surfaced the fact that the 1,298 "fills" of the prior baseline were 95% phantom and the 122-trade baseline was really 17 trades.

**Findings parked in audit**: C2b (batched INSERTs) tried + reverted — only 1.6% speedup. `run_in_executor` removal saved 6% — partial answer to "real fulltest bottleneck." Remaining ~94% wall clock is somewhere else (replay, Redis ops, OMS rejection path); not yet investigated. C5 (cash check) fixed.

## Deferred (don't work on these yet)

Real gaps, but not worth the effort until strategies post positive expectancy.

- **External alert channels** (email/SMS/Slack) — was "Iteration 12" in older planning. Audit C1.
- **Multi-market (EU/Asia)** — design doc roadmap, never shipped. Audit B4.
- **Horizontal scaling / worker partitioning** — design doc only. Audit B5.
- **`on_tick` / `on_regime_change` strategy hooks** — design doc only. Audit B3.
- **PaperBroker volume realism** — audit C3.
- **`axtrade` package vs `meridian` repo name** — cosmetic. Audit C4.

## History

- What was built, when: [`docs/PROGRESS.md`](docs/PROGRESS.md).
- Original Jan v2.0 design vision: [`next-gen-trading-platform-design.md`](next-gen-trading-platform-design.md). Useful for component-level design context, but several sections have drifted from reality — the audit's §B1–B5 list every divergence.
- Old iteration plans (3, 4, 5, 6, 7, 8, 9, 11): [`docs/iterations/archive/`](docs/iterations/archive/).
