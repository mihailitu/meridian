# Roadmap

> Where the project actually is, what's next, and what's deferred.
> For deeper detail on any item, follow the link to the audit or work doc.

_Last refreshed: 2026-05-10._

## Today

- **Pipeline works end-to-end** in paper / fulltest mode: gateway → aggregator (with SMA, RSI, BB, ATR, regime) → strategies → OMS → DB. Web UI shows positions, P&L, alerts.
- **Strategies are not yet profitable.** Last clean baseline: -0.94% return / 30.7% win rate over 6 months on 5 symbols + S&P discovery (`data/fulltest_results/fulltest_20260218_221730.txt`).
- **Strategy rewrites merged to `main`** (commits `27063ed`, `e60dc84`, `b5fe036`, `94042bb`): regime-aware entries/exits for all four rule-based strategies plus per-strategy `max_positions`. Validation fulltest at baseline params is still owed (the original validation was killed at 57min). Detail: [`docs/strategy-logic-fixes.md`](docs/strategy-logic-fixes.md).
- **Data inventory**: `data/historical/` holds 1,447 unique symbols across two periods (2024-08 → 2025-08 and 2025-08 → 2026-02), ~6.3 GB. Covers full S&P 1500 universe in both windows. Validation gate is fully unblocked — no download step needed.
- **Active plan**: phased execution doc at [`docs/active-plan.md`](docs/active-plan.md). Implementation work tracked on branch `validation-and-improvements`.

## What's next (chop order)

In rough priority. Item codes (A1, B2, etc.) are the audit's IDs — see [`docs/AUDIT-2026-05-02.md`](docs/AUDIT-2026-05-02.md) for evidence and fix direction. Full phase detail in [`docs/active-plan.md`](docs/active-plan.md).

| # | Item | Why now | Status |
|---|------|---------|--------|
| 1 | Strategy followups (momentum gate, mean-reversion regression, multi-timeframe, pairs) | Validation done 2026-05-10: total return -0.94% → +0.05%, but mean_reversion regressed (PF 0.61 → 0.35) and momentum still 0 entries. Per-strategy detail in `strategy-logic-fixes.md` | next up |
| 2 | Investigate real fulltest bottleneck | C2b (batched INSERTs) tried + reverted: only 1.6% speedup, caused discovery non-determinism. INSERT was not the dominant cost. Find what actually is | not started |
| 3 | Mark-to-market Sharpe (A1) | Sharpe always 0.00; can't compare strategies on risk-adjusted return | not started |
| 4 | Cheap cleanup: rename "regime" → "trend regime" (B1) + delete `ml/` (B2) | Stop the docs from drifting; remove 966 LoC of hand-rolled GD that's disabled in config | not started |
| 5 | Expand testing: 18-month window + S&P 1500 universe | Per user: tune on 6mo first, then expand. Data already on disk | not started |
| 6 | IBKR `add_symbols` (A3) + paper integration test (C2) | Gate before any live IBKR submission | not started |

**Validation result (2026-05-10)**: post-rewrite baseline is `data/fulltest_results/fulltest_20260510_105510.txt` — 5 named symbols + discovery, $100K, 6 months. Final equity $100,046 (+0.05%), 122 trades, 29.5% WR, 0.91 PF. Wall clock 37min. Compared to the pre-rewrite 480-symbol baseline (`fulltest_20260218_221730.txt`): not strictly apples-to-apples (different symbol set, much higher discovery scan rate), but rewrites moved net P&L from -$935 to +$46.

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
