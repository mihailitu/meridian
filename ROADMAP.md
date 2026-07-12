# Roadmap

> Where the project actually is, what's next, and what's deferred.
> For deeper detail on any item, follow the link to the audit or work doc.

_Last refreshed: 2026-07-12 (phase 5 underway)._

## Today

- **Phase 5 (audit fixes) is underway** on branch `phase5-audit-fixes`. A fresh
  whole-project audit ([`docs/AUDIT-2026-07-12.md`](docs/AUDIT-2026-07-12.md)) found that
  the phase-3 accounting/clock fixes hold, but (a) the **data layer under the harness was
  broken** — split-unadjusted downloads, duplicated boundary days, and a manifest bug that
  made the discovery_momentum IS/OOS comparison structurally invalid (**that verdict row is
  withdrawn pending re-run**); (b) the **live multi-process path could not work** — no fill
  routing to strategies, a dead IBKR tick path, in-process-only discovery scores; (c) the
  **API was an unauthenticated remote control on 0.0.0.0**. Five iterations have landed
  fixing all P0s and 6/11 P1s; an adjusted full-universe re-download is in progress with an
  IS/OOS re-certification run to follow — status, commands, and pickup notes in
  [`docs/phase5-audit-fixes.md`](docs/phase5-audit-fixes.md).
- **The per-strategy verdict table below is under re-certification.** The five
  static-symbol strategy verdicts are expected to survive (their windows appear split-free);
  the discovery_momentum row is known-invalid as evidence (audit P0-3). Do not cite the
  table until the `post-data-fixes` re-run lands.
- **Phase 4 (platform pivot) is complete — all six work iterations landed 2026-07-03**
  (branch `phase4-platform-pivot`, plan + findings in
  [`docs/phase4-platform-pivot.md`](docs/phase4-platform-pivot.md)). The strategy-search
  phase concluded as **Option B**; the success criterion is a **trustworthy
  strategy-evaluation platform with live paper-trading capability**. What landed:
  green test baseline (4 long-standing test failures fixed) with **all strategies shipped
  `enabled: false`**; the ML stack deleted end-to-end (audit B2); IBKR dynamic subscribe so
  the discovery→trading bridge no longer silently no-ops on the production broker (A3);
  an end-to-end live-paper integration test (`make test-integration`, C2); and an optional
  PaperBroker volume-participation cap (`oms.max_volume_participation`, C3) whose off-state
  was calibration-verified to the cent against raw parquet.
- **The integration test caught F10 on its first run** — OrderManager stamped SUBMITTED
  after the PaperBroker's synchronous fill had already persisted FILLED, so every
  immediately-filled paper order read `status='submitted'` forever (fills/positions were
  correct, which is why fills-based analytics never noticed). Fixed with a regression test.
  Second time a calibration/integration gate has caught a real bug the unit suite missed
  (phase 3: F6/F7).
- **Platform state**: suite 987 green + integration test 3× deterministic; live-IBKR
  validation of the dynamic-subscribe path explicitly remains (needs a TWS/Gateway
  account). There is deliberately no enabled strategy — see the per-strategy table below.
- **The backtest harness is trustworthy — and that changed every prior conclusion.**
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

## What's next

**Resolved 2026-07-03: Option B.** The fork (A: survivorship-clean data + one cross-sectional
momentum trial; B: conclude strategy search, pivot to platform) is discussed at the end of
[`docs/phase3-trustworthy-harness.md`](docs/phase3-trustworthy-harness.md). Rationale for B:
five-for-five honest failures is a result, not bad luck (phase-3 finding F5 — no edge exists
at this horizon for this stack); the remaining documented anomaly family (cross-sectional
momentum) would at best replicate an ETF factor exposure; the demonstrated value is the
platform + calibrated harness. Option A's *data work* survives as an optional, unapproved
iteration in the phase-4 plan — it is a harness-quality feature, not a bot revival.

**Phase 4 is done.** What remains open, in rough priority order:

1. **Live paper validation run** — the stack is integration-tested in-process; the next
   confidence step is running the real services (`scripts/start-all.sh`, mock or Alpaca
   adapter, paper mode) for a market day and checking the dashboard/DB against expectations.
   Cheap, and exercises the exact `make run*` path.
2. **Live-IBKR validation of dynamic subscribe** — needs a TWS/IB Gateway account wired up;
   until then A3 is fake-verified only.
3. **External alert channels (audit C1)** — the platform's first genuinely new feature
   since the pivot; email first.
4. **Optional iteration A (point-in-time universe data)** — documented in the phase-4 plan,
   still not approved. Only worth it if a cross-sectional strategy trial is ever wanted;
   it upgrades the harness from "falsification-capable on gateway symbols" to
   "falsification-capable on universes".

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

Real gaps, not scheduled.

- **External alert channels** (email/SMS/Slack) — was "Iteration 12" in older planning. Audit
  C1. Revisit after phase 4 lands.
- **`axtrade` package vs `meridian` repo name** — cosmetic. Audit C4.

Note: PaperBroker volume realism (audit C3) moved out of deferred — it is phase-4 iteration 6.

## Retired (don't resurrect without a new written case)

Design-doc ambitions retired with the 2026-07-03 platform pivot. There is no strategy to
scale, and none of these change that.

- **Multi-market (EU/Asia)** — audit B4.
- **Horizontal scaling / worker partitioning / millisecond-latency targets** — audit B5.
- **`on_tick` / `on_regime_change` strategy hooks** — audit B3.
- **ML/AI strategy layer** — audit B2; `ml/` deletion is phase-4 iteration 3.

## History

- Phase 5 (audit fixes, in progress): [`docs/phase5-audit-fixes.md`](docs/phase5-audit-fixes.md); audit: [`docs/AUDIT-2026-07-12.md`](docs/AUDIT-2026-07-12.md).
- Phase 4 (platform pivot: B2/A3/C2/C3, F10 fix): [`docs/phase4-platform-pivot.md`](docs/phase4-platform-pivot.md).
- Phase 3 (harness trust + strategy verdicts): [`docs/phase3-trustworthy-harness.md`](docs/phase3-trustworthy-harness.md).
- Phase 2 era plans: [`docs/active-plan.md`](docs/active-plan.md) (superseded by phase 3 doc).
- What was built, when: [`docs/PROGRESS.md`](docs/PROGRESS.md).
- Original Jan v2.0 design vision: [`next-gen-trading-platform-design.md`](next-gen-trading-platform-design.md). Useful for component-level design context, but several sections have drifted from reality — the audit's §B1–B5 list every divergence.
- Old iteration plans (3, 4, 5, 6, 7, 8, 9, 11): [`docs/iterations/archive/`](docs/iterations/archive/).
