# Roadmap

> Where the project actually is, what's next, and what's deferred.
> For deeper detail on any item, follow the link to the audit or work doc.

_Last refreshed: 2026-05-12._

## Today

- **Pipeline works end-to-end** in paper / fulltest mode: gateway → aggregator (with SMA, RSI, BB, ATR, regime) → strategies → OMS → DB. Web UI shows positions, P&L, alerts.
- **OMS re-entry bug fixed (Phase 2.7, `08c9224`).** Closed positions weren't clearing `closed_at` on re-entry; new fills pyramided onto the stale row, creating "ghost" positions invisible to `get_open_positions` but consuming real PaperBroker cash. Affected any strategy that closed and re-entered the same symbol. Patched `_update_position` to treat closed rows as fresh, plus repository upsert now persists `side` / `opened_at` changes. Two regression tests cover same-side and side-flip re-entry. Detail: [`docs/strategy-logic-fixes.md`](docs/strategy-logic-fixes.md).
- **Universe narrowing + IS/OOS validation plumbing landed (Phase 2.8, `8ed17f1`).** `multi_timeframe`, `mean_reversion`, `momentum` now honor an `allowed_symbols` config — the orchestrator restricts them to the gateway 5 (previously they traded 50+ discovery-fed symbols too). New `fulltest oos` subcommand runs two backtests back-to-back and emits a side-by-side comparison (per-strategy IS vs OOS PnL / PF / WR / Sharpe / verdict). YAML strategy-parameter overrides via `--strategy-overrides`. 29 new unit tests.
- **Strategies have no demonstrated edge** after the OMS fix + B/D shipped. IS year (2024-08 → 2025-08) on AAPL/MSFT/GOOGL/AMZN/NVDA with discovery on: 3 of 4 strategies fail IS outright; the 4th (`mean_reversion`, IS PF 1.29) collapses OOS to PF 0.27 — textbook in-sample overfit. Detail: [`data/fulltest_results/oos_comparison_20260512_211515.txt`](data/fulltest_results/oos_comparison_20260512_211515.txt).
- **Data inventory**: `data/historical/` holds 1,447 unique symbols across two periods (2024-08 → 2025-08 and 2025-08 → 2026-02), ~6.3 GB. Covers full S&P 1500 universe in both windows.
- **Active plan**: phased execution doc at [`docs/active-plan.md`](docs/active-plan.md).

## What's next (chop order)

Priorities shifted on 2026-05-12. The OOS validation killed the "tune the existing rule-based strategies" path that was item #1 — three of four fail IS, the fourth fails OOS, and no parameter tweak lifts PF from 0.17 to 1.0. The path forward is one of three branches, listed below in the order I'd recommend. Full discussion in [`docs/active-plan.md`](docs/active-plan.md) Phase 3.

| # | Item | Why now | Status |
|---|------|---------|--------|
| 1 | **Diagnose `discovery_momentum` IS/OOS asymmetry** | IS PF 0.04 with only 69 trades vs OOS PF 0.56 with 485 trades — too lopsided to be sample variance. Possible bug in scoring on the 2024-08→2025-08 window, possible regime mismatch, possible discovery feed differs sharply between periods. One focused session before discarding the only strategy that ever showed edge. | next up |
| 2 | **Pick a research-backed signal and run it through the OOS comparison** | The B/D plumbing is now ready for any new strategy. Candidates: overnight reversal (buy close, sell open), end-of-day momentum, opening-drive fade. Implement one, drop the other four enabled strategies from the run, see if it survives IS+OOS. | gated on #1 outcome |
| 3 | **Accept that strategy-design isn't the project goal — pivot to architecture** | Pipeline + OOS validation work; if the project's real value is the platform (paper trading, monitoring, multi-market, ML feature layer), call the rule-based-strategies experiment closed and move to A3 (IBKR `add_symbols`) + C2 (paper integration test). Trades the "build a profitable bot" framing for "build a working trading platform." | alternative path |
| 4 | B2: delete `ml/` (966 LoC of disabled hand-rolled GD) | Cheap simplification; stops "what's this for?" friction. ~2 hours, orthogonal to #1–#3 | not started |
| 5 | Expand testing: 18-month window + S&P 1500 universe | Worth it only if a strategy clears IS+OOS on the current set first. Data already on disk. | gated on a strategy surviving #1 or #2 |
| 6 | IBKR `add_symbols` (A3) + paper integration test (C2) | Gate before any live IBKR submission. Part of branch #3 if the user picks the platform pivot. | gated on intent (see #3) |

**Per-strategy state (post-Phase 2.8, IS year vs OOS half-year, discovery on, narrowed universe)**:

| Strategy | IS Trades | IS PF | IS P&L | OOS PF | OOS P&L | Verdict |
|----------|----------:|------:|-------:|-------:|--------:|---------|
| `discovery_momentum` | 69 | 0.04 | -$148 | 0.56 | -$1,975 | IS_UNPROFITABLE — but IS sample is suspicious, see #1 |
| `mean_reversion` | 78 | **1.29** | **+$714** | 0.27 | -$606 | BROKEN — passes IS, OOS collapse is textbook overfit |
| `multi_timeframe` | 613 | 0.24 | -$10,773 | 0.28 | -$5,159 | IS_UNPROFITABLE — no edge at the signal level |
| `pairs` | 7 | 0.00 | -$253 | 0.01 | -$235 | IS_UNPROFITABLE — too low-frequency to evaluate |

**Phase 2.7 + 2.8 deliverables** (commits `08c9224`, `8ed17f1`): OMS re-entry bug fix; `allowed_symbols` filter on three rule-based strategies; orchestrator wires gateway symbols into the filter; YAML `strategy_overrides` for manual parameter iteration; `fulltest oos` subcommand + comparison module + text/JSON report. The new validation reports in `data/fulltest_results/` (e.g., `oos_comparison_20260512_211515.txt`) are the new regression baseline.

**Findings parked in audit**: C2b (batched INSERTs) tried + reverted — only 1.6% speedup. `run_in_executor` removal saved 6%. Remaining ~94% wall clock unaccounted-for; not investigated. C5 (cash check) fixed in 2.6.

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
