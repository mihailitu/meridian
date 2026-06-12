# Roadmap

> Where the project actually is, what's next, and what's deferred.
> For deeper detail on any item, follow the link to the audit or work doc.

_Last refreshed: 2026-06-13._

## Today

- **The backtest harness is now trustworthy — and that changed every prior conclusion.**
  Phase 3 (branch `phase3-harness-fixes`, plan + findings in
  [`docs/phase3-trustworthy-harness.md`](docs/phase3-trustworthy-harness.md)) calibrated the
  fulltest pipeline against hand-computable benchmarks and found/fixed five serious harness
  bugs: discovery scored the universe on end-of-window data (F1) with a sticky max-score cache
  (F2); pipeline shutdown truncated every run's tail — old runs covered an unknown *prefix* of
  their window (F7); equity ignored open positions and commissions (F6); analytics were
  realized-only with a cost-basis curve — the source of the absurd −24/−43 Sharpes (F8); and
  the replay producer outran the sim clock so discovery-fed symbols joined at the wrong time
  or never (F9). Calibration now passes to the cent: year-long buy_hold reproduces the
  hand-computed $108,595.57 exactly, with plausible Sharpe (0.69 raw) and drawdown (13.15%).
- **Honest verdict: every strategy loses.** Post-fix IS/OOS comparison
  (`data/fulltest_results/oos_comparison_20260613_*.txt`, label `post-harness-fixes`):
  discovery_momentum IS PF 0.42 / OOS PF 0.45 — the old 0.04-vs-0.56 asymmetry (item #1 of the
  previous roadmap) was the bugs, not regime. mean_reversion's celebrated IS PF 1.29 is 0.40
  in the honest harness — the only "edge" ever measured was a truncation artifact.
  A new daily-horizon strategy (overnight reversal, the previous item #2) was implemented,
  tested, and failed IS at PF 0.50, and 0.63 after its one allowed tuning pass. momentum
  trades 0 times even with its config bug fixed.
- **New harness capabilities**: `buy_hold` calibration benchmark + `--strategies` selection
  flag; mark-to-market daily equity curve; per-strategy unrealized P&L in reports;
  `Data Through` coverage guard; producer pacing; sim-time-bounded discovery on seeded daily
  universe bars; per-scan score decay. ~120 new unit tests across phase 3.
- **Data inventory**: `data/historical/` holds 1,447 unique symbols across two periods
  (2024-08 → 2025-08 and 2025-08 → 2026-02), ~6.3 GB. **Known limitation (F4): downloaded
  from today's index membership — survivorship-biased.** Universe-wide long results are upper
  bounds only.

## What's next (decision pending)

The strategy-search question is now a fork, discussed at the end of
[`docs/phase3-trustworthy-harness.md`](docs/phase3-trustworthy-harness.md):

| Option | What | Cost | When it makes sense |
|--------|------|------|---------------------|
| **A** | Survivorship-clean data: reconstruct point-in-time S&P membership (Wikipedia constituent-change history) + pre-window daily seeding; then give cross-sectional 12-1 momentum an honest trial | ~1–2 days + reruns | If "build a profitable bot" still gets one properly-resourced attempt |
| **B** | Conclude the strategy-search phase; pivot to platform (previous item #3): IBKR `add_symbols` (A3), paper integration test (C2), delete `ml/` (B2) | starts immediately | Five-for-five honest failures is a result; the platform + trustworthy harness is the demonstrated value |

Recommendation as of 2026-06-13: **B**, unless A is explicitly wanted. Either way B2
(delete `ml/`, ~2h) is cheap and orthogonal — do it whenever.

**Per-strategy state (post-harness-fixes, IS year vs OOS half-year, discovery on, narrowed universe)**:

| Strategy | IS Trades | IS PF | IS P&L | OOS Trades | OOS PF | OOS P&L | Verdict |
|----------|----------:|------:|-------:|-----------:|-------:|--------:|---------|
| `discovery_momentum` | 1,506 | 0.42 | -$13,530 | 6,659 | 0.45 | -$21,938 | DEAD — consistent, large-sample, unprofitable |
| `mean_reversion` | 319 | 0.40 | -$4,061 | 164 | 0.36 | -$2,368 | DEAD — old IS PF 1.29 was a harness artifact |
| `multi_timeframe` | 3,810 | 0.21 | -$64,634 | 1,933 | 0.21 | -$38,481 | DEAD — no edge at the signal level |
| `pairs` | 12 | 0.06 | -$824 | 3 | 0.01 | -$235 | DEAD — too low-frequency to evaluate, loses anyway |
| `momentum` | 0 | — | — | 0 | — | — | DEAD — gates never co-fire even with fixed config |
| `overnight_reversal` (new) | 127 | 0.63 | -$2,479 | — | — | — | DEAD — failed IS after one tuning pass; OOS never earned |

All six should ship `enabled: false` for any non-research run.

**Findings parked in audit**: C2b (batched INSERTs) tried + reverted — only 1.6% speedup.
`run_in_executor` removal saved 6%. C5 (cash check) fixed in 2.6. Note: wall-clock per run
roughly doubled with the F7 drain fix — old timings measured truncated runs.

## Deferred (don't work on these yet)

Real gaps, but not worth the effort until the Option A/B decision lands.

- **External alert channels** (email/SMS/Slack) — was "Iteration 12" in older planning. Audit C1.
- **Multi-market (EU/Asia)** — design doc roadmap, never shipped. Audit B4.
- **Horizontal scaling / worker partitioning** — design doc only. Audit B5.
- **`on_tick` / `on_regime_change` strategy hooks** — design doc only. Audit B3.
- **PaperBroker volume realism** — audit C3.
- **`axtrade` package vs `meridian` repo name** — cosmetic. Audit C4.

## History

- Phase 3 (harness trust + strategy verdicts): [`docs/phase3-trustworthy-harness.md`](docs/phase3-trustworthy-harness.md).
- Phase 2 era plans: [`docs/active-plan.md`](docs/active-plan.md) (superseded by phase 3 doc).
- What was built, when: [`docs/PROGRESS.md`](docs/PROGRESS.md).
- Original Jan v2.0 design vision: [`next-gen-trading-platform-design.md`](next-gen-trading-platform-design.md). Useful for component-level design context, but several sections have drifted from reality — the audit's §B1–B5 list every divergence.
- Old iteration plans (3, 4, 5, 6, 7, 8, 9, 11): [`docs/iterations/archive/`](docs/iterations/archive/).
