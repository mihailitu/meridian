# Roadmap

> Where the project actually is, what's next, and what's deferred.
> For deeper detail on any item, follow the link to the audit or work doc.

_Last refreshed: 2026-05-04._

## Today

- **Pipeline works end-to-end** in paper / fulltest mode: gateway → aggregator (with SMA, RSI, BB, ATR, regime) → strategies → OMS → DB. Web UI shows positions, P&L, alerts.
- **Strategies are not yet profitable.** Last clean baseline: -0.94% return / 30.7% win rate over 6 months on 5 symbols + S&P discovery (`data/fulltest_results/fulltest_20260218_221730.txt`).
- **Active branch**: `strategy-logic-fixes` — entries/exits rewritten for all four rule-based strategies (momentum, multi-timeframe, mean-reversion, pairs) plus per-strategy `max_positions`. Validation fulltest was killed at 57min before report generation, so an apples-to-apples comparison against the baseline is still owed. Detail: [`docs/strategy-logic-fixes.md`](docs/strategy-logic-fixes.md).

## What's next (chop order)

In rough priority. Item codes (A1, B2, etc.) are the audit's IDs — see [`docs/AUDIT-2026-05-02.md`](docs/AUDIT-2026-05-02.md) for evidence and fix direction.

| # | Item | Why now | Status |
|---|------|---------|--------|
| 1 | Strategy logic rewrites (P1) | Without positive expectancy nothing else matters | landed; validation fulltest owed |
| 2 | Batch aggregator INSERTs (C2b) | Fulltest is 60–90+ min — blocks iteration on #1 | not started |
| 3 | Mark-to-market Sharpe (A1) | Sharpe currently always 0.00; can't compare strategies on risk | not started |
| 4 | IBKR `add_symbols` (A3) | Discovery→trading bridge silently no-ops on IBKR | not started |
| 5 | Rename "regime" → "trend regime" (B1) | Honest naming; macro regime never built | not started |
| 6 | Delete `ml/` (B2) | Hand-rolled GD; not used; just noise | not started |
| 7 | IBKR paper integration test (C2) | Gate before any live order | not started |

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
