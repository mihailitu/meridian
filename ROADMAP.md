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
| 1 | **The 12-day trading cliff** | Phase 2.5 surfaced: in every fulltest run, all 1,298 fills happen in the first 12 simulated days (Aug 1-12 2025). After that, strategies hit position-value caps and never trade again over the remaining 5.5 months. Every prior "6-month" result is really 12 days. Without this fix, no other tuning is meaningful | next up |
| 2 | PaperBroker cash check | Related root cause: broker accepts buys without checking cash. Total open position book reaches $4.2M of phantom cost on $100K capital. Until this is fixed, mark-to-market equity is fantasy and we can't compute a real risk metric | next up |
| 3 | Mean-reversion deep dive | PF 0.59 still net-loss. Per-symbol breakdown (Phase 2.5) shows it's structural (each closed trade is on a different symbol, no bad-apple) | gated on #1 |
| 4 | B2: delete `ml/` (966 LoC of disabled hand-rolled GD) | Cheap simplification; stops "what's this for?" friction. ~2 hours, orthogonal | not started |
| 5 | Momentum redo | Current relaxed gate trades only on discovery-fed names where `discovery_momentum` already does it better | gated on #1 |
| 6 | Expand testing: 18-month window + S&P 1500 universe | Per user: tune on 6mo first, then expand. Data already on disk | gated on strategies actually trading the full period |
| 7 | IBKR `add_symbols` (A3) + paper integration test (C2) | Gate before any live IBKR submission | gated on strategies posting positive expectancy |

**Per-strategy state (post-PR)**: `discovery_momentum` PF 1.63 (+$265) ✓, `multi_timeframe` PF 1.17 (+$295) ✓, `mean_reversion` PF 0.59 (-$306) ↑ from 0.35, `pairs` 1 trade -$196, `momentum` 0 entries (gate too strict; relaxation tried + reverted because it traded only on discovery names with worse logic than `discovery_momentum`). **Caveat**: all of these numbers come from the first 12 simulated days, not the full 6 months — see #1 above.

**Phase 2.5 deliverables** (PR `validation-and-improvements`): per-symbol P&L breakdown in every strategy's report section; portfolio Sharpe is now meaningful (0.91 in latest run); fills timestamped on simulated bar time so analytics see the simulated period; per-strategy Sharpe suppressed to N/A when sparse (the sparse-data symptom of the 12-day cliff).

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
