# Roadmap

> Where the project actually is, what's next, and what's deferred.
> For deeper detail on any item, follow the link to the audit or work doc.

_Last refreshed: 2026-05-10._

## Today

- **Pipeline works end-to-end** in paper / fulltest mode: gateway → aggregator (with SMA, RSI, BB, ATR, regime) → strategies → OMS → DB. Web UI shows positions, P&L, alerts.
- **Strategies barely break even.** Current canonical baseline: +0.06% return / 31.97% WR / 0.93 PF over 6 months on 5 symbols + S&P discovery (`data/fulltest_results/fulltest_20260510_210714.txt`). Post-rewrite + Phase 2 mean-reversion fix.
- **Strategy rewrites merged to `main`** (`27063ed`, `e60dc84`, `b5fe036`, `94042bb`) plus the `validation-and-improvements` PR (mean_reversion upper-band exit + drop `run_in_executor` from strategy runner). Detail: [`docs/strategy-logic-fixes.md`](docs/strategy-logic-fixes.md).
- **Data inventory**: `data/historical/` holds 1,447 unique symbols across two periods (2024-08 → 2025-08 and 2025-08 → 2026-02), ~6.3 GB. Covers full S&P 1500 universe in both windows.
- **Active plan**: phased execution doc at [`docs/active-plan.md`](docs/active-plan.md).

## What's next (chop order)

In rough priority. Item codes (A1, B2, etc.) are the audit's IDs — see [`docs/AUDIT-2026-05-02.md`](docs/AUDIT-2026-05-02.md) for evidence and fix direction. Full phase detail in [`docs/active-plan.md`](docs/active-plan.md).

| # | Item | Why now | Status |
|---|------|---------|--------|
| 1 | **A1 Mark-to-market Sharpe + per-symbol P&L breakdown in fulltest report** | Sharpe always reads 0.00 so we can't compare strategies on risk; per-symbol breakdown would show whether mean_reversion's loss is structural or a bad-apple problem. Both make every future tuning decision sharper | next up |
| 2 | Mean-reversion deep dive | PF 0.59 still net-loss (-$306). With #1 we'll know whether it's a structural issue or 1-2 bad symbols dragging it down | gated on #1 |
| 3 | B2: delete `ml/` (966 LoC of disabled hand-rolled GD) | Cheap simplification; stops "what's this for?" friction. ~2 hours | not started |
| 4 | Momentum redo | Current relaxed gate trades only on discovery-fed names where `discovery_momentum` already does it better. Either disable momentum or repurpose for the named-symbol universe only | gated on #1, #2 |
| 5 | Expand testing: 18-month window + S&P 1500 universe | Per user: tune on 6mo first, then expand. Data already on disk | gated on strategies posting positive expectancy |
| 6 | IBKR `add_symbols` (A3) + paper integration test (C2) | Gate before any live IBKR submission | gated on strategies posting positive expectancy |

**Per-strategy state (post-PR)**: `discovery_momentum` PF 1.63 (+$265) ✓, `multi_timeframe` PF 1.17 (+$295) ✓, `mean_reversion` PF 0.59 (-$306) ↑ from 0.35, `pairs` 1 trade -$196, `momentum` 0 entries (gate too strict; relaxation tried + reverted because it traded only on discovery names with worse logic than `discovery_momentum`).

**Findings parked in audit**: C2b (batched INSERTs) tried + reverted — only 1.6% speedup. `run_in_executor` removal saved 6% — that's the partial answer to "real fulltest bottleneck." Remaining ~94% wall clock is somewhere else (replay, Redis ops, OMS rejection path); not yet investigated.

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
