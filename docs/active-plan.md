# Plan — Doc refresh + comprehensive test & improvements roadmap

## Context

Today (2026-05-10), the project is paused at a single decision-blocking gate: the strategy-logic rewrites landed on `main` (commits `27063ed`, `e60dc84`, `b5fe036`, `94042bb`) but the validation fulltest was killed at 57min and never re-run. ROADMAP.md still says `strategy-logic-fixes` is the "active branch" — it isn't, it merged. The historical data needed to validate (1,447 symbols × 2 periods, 2024-08→2025-08 and 2025-08→2026-02, ~6.3 GB) is already on disk in `data/historical/`, so the validation gate is fully unblocked.

User intent (explicit): tune strategies on the existing 6-month dataset first; once results look good, expand the data and try paper trading. Out-of-sample / overfitting concerns are accepted for now.

This plan covers two things: (1) refresh the docs to reflect actual state, and (2) lay out a phased test + improvement roadmap from validation through paper trading.

---

## Phase -1 — Setup (do first, before any code or doc edits)

1. **Copy this plan into the project repo** as a tracked working doc:
   - Source: `/home/mihai/.claude/plans/update-the-docs-and-ethereal-dijkstra.md`
   - Destination: `/home/mihai/workspace/meridian/docs/active-plan.md`
   - Why: keeps the plan visible in the project tree alongside ROADMAP/AUDIT/strategy-logic-fixes. The `~/.claude/plans/` copy is the harness's location; the in-repo copy is for tracking and reference.
2. **Create a new branch** for implementation work, off `main`:
   - Suggested name: `validation-and-improvements` (covers both Phase 0+1 and the followup phases). Adjust if you prefer a narrower scope per phase.
   - Command: `git checkout -b validation-and-improvements`
   - All code changes (C2b, strategy tuning, A1, B1/B2, IBKR work) land on this branch. Doc updates land here too so they're reviewable together.
3. **Confirm `make dev` venv is healthy** before kicking off Phase 0's long fulltest run — `pyarrow`/`pandas` were missing from `.venv` when I tested. The fulltest pipeline reads parquet through project code so it's likely fine, but worth a `.venv/bin/python -c "import pyarrow"` smoke check first.

---

## Part A — Doc updates

Three doc files drift from reality. Updates are scoped and minimal — no rewrites.

### A1. `ROADMAP.md`

- **Refresh date**: `2026-05-04` → `2026-05-10`
- **"Active branch" line (line 12)**: the rewrites are on `main` now (`git log` confirms). Replace with: "Strategy rewrites merged to `main`. Validation fulltest at baseline params still owed; historical data already in `data/historical/` so the run is unblocked."
- **"What's next" table**: re-prioritize per user intent (see Part B). Validation + C2b run in parallel as #1 (background slow run + foreground batching work), then strategy followups (#2), A1 mark-to-market Sharpe (#3), B1/B2 cleanup (#4), expand data window/universe (#5), IBKR add_symbols + paper integration (#6).
- **Add a "Data inventory" line under "Today"**: 1,447 symbols × 2 periods = ~6.3 GB on disk; covers full S&P 1500 universe; both 2024-08→2025-08 and 2025-08→2026-02 windows present.

### A2. `docs/strategy-logic-fixes.md`

Branch is merged, but the "Open issues from the partial fulltest run" section is the live work queue. Keep the file but:

- Update Status header: branch merged to `main` on 2026-05-04; validation still owed.
- Promote "Followups suggested by the partial run" to a top-level section: **Followup tuning items** (momentum entry gate too strict, multi-timeframe re-entry cooldown, pairs validation).
- Drop the "Verification" section's "compare against fulltest_20260218_221730.txt" framing — keep it but note it's the regression baseline going forward.

### A3. `docs/AUDIT-2026-05-02.md`

Mostly still accurate. Two small additions:

- **A1 status**: still open — bar-price plumbing not done.
- **C2b status**: still open — verified `aggregator/service.py:187` still calls `insert_bar()` per bar, while `bulk_insert_bars` (defined at `common/db.py:288-346`) is only used in fulltest pre-seed (`fulltest/orchestrator.py:345,350`).

`docs/PROGRESS.md` does not need an update yet — it's a history log and there's nothing new to log until validation completes.

---

## Part B — Test & improvements plan (phased)

Each phase has a clear exit criterion. Don't move to the next phase until the current one's exit is met.

### Phase 0+1 — Validation (background) + C2b batching (foreground), in parallel — DONE 2026-05-10

**Outcome**:
- **Phase 0 (validation)**: complete. Report saved at `data/fulltest_results/fulltest_20260510_105510.txt`. Total return -0.94% (pre-rewrite baseline) → +0.05% (post-rewrite). Per-strategy detail in [`strategy-logic-fixes.md`](strategy-logic-fixes.md). Wall clock ~37min, not 60-90min.
- **Phase 1 (C2b)**: implemented + 6 unit tests passed, but reverted. Re-run with batching delivered only 1.6% speedup (premise that INSERT was the bottleneck was wrong) and caused discovery to read stale data, producing a different fed-symbol set between runs. Net-negative change. Detail in [`AUDIT-2026-05-02.md`](AUDIT-2026-05-02.md) §C2b.

**Replacement work item**: investigate the actual fulltest bottleneck before any further optimization. Profile a representative run; identify the dominant cost (indicator calc, strategy eval, replay tick generation, or something else).

Original phase plan kept below for context.



**0 (background, ~60-90min, no babysitting)** — validation gate:

- Run fulltest at exactly baseline params: `--start 2025-08-01 --end 2026-02-01 --symbols AAPL MSFT GOOGL AMZN NVDA --capital 100000`. Discovery enabled (S&P 500 universe).
- Save report in `data/fulltest_results/` and label clearly (e.g., `fulltest_post-rewrite-baseline_<timestamp>.txt`).
- Compare side-by-side against `data/fulltest_results/fulltest_20260218_221730.txt`. Targets from `strategy-logic-fixes.md`:
  - Win rate: 30.7% → 35%+
  - Mean reversion profit factor: 0.61 → higher
  - Pairs: more than 1 trade
  - Discovery_momentum: regression check (remain profitable)
- Important: the slow-path validation must run **before** C2b lands, or we lose the apples-to-apples comparison (different code path = different numbers possible).

**1 (foreground, ~1 day)** — C2b batched aggregator INSERTs:

- Buffer N completed bars in `aggregator/service.py:_process_completed_bar` and flush via existing `bulk_insert_bars` (`common/db.py:288-346`). Reuse, don't rewrite.
- Flush triggers: buffer size threshold (try 200) **or** time-based timer (e.g., every 2s) so live mode latency stays bounded.
- Verify Redis publish (`aggregator/service.py:195`) still happens on completion — only the DB write batches.
- After landing C2b, re-run the same fulltest. Should produce identical fills/P&L (allow floating-point noise on totals; exact fill counts and timestamps should match) but in <10min.

**Files to touch**: `src/axtrade/aggregator/service.py` (mainly `_process_completed_bar` and a buffer flush helper). `src/axtrade/common/db.py` is reused as-is.

**Coordination note**: the slow-path validation must finish (or be confirmed running on un-modified code) before merging C2b — otherwise we don't know which code path produced the baseline numbers.

**Exit**:
- Slow-path validation report saved with delta written vs. pre-rewrite baseline. Record numbers, not vibes.
- C2b merged. Validation re-runs in <10min wall clock with matching fills/P&L.

### Phase 2 — Strategy followups — DONE 2026-05-10 (PR `validation-and-improvements`)

**Outcome (post-PR baseline `fulltest_20260510_210714.txt`)**: portfolio +0.06% / 31.97% WR / 0.93 PF. +$11 net P&L gain over the pre-PR validation.

What landed in the PR:
- `mean_reversion`: reverted middle-band exit back to upper-band. PF 0.35 → **0.59**, avg winner $16 → $35, WR 27.5% → 33.3%. Still net-loss but trajectory is right.
- `strategies/runner.py`: dropped `loop.run_in_executor` from per-bar strategy dispatch. ~5% wall-clock speedup, deterministic strategy order. Strategy P&L unchanged within natural noise (~$3).

What was tried and reverted (full detail in `strategy-logic-fixes.md` followups):
- **Momentum gate relaxation** (`trend_strength_min` 30→20, RSI cross window 1→5 bars): enabled 6 trades but they net-lost $135. Strategy was trading exclusively on discovery-fed names, competing with `discovery_momentum` (which is profitable on those names). Reverted.
- **Momentum stop tighten** (3% → 2%): no-op. Losses exit via regime-flip / RSI, not stop-loss. Reverted.

What didn't ship:
- `multi_timeframe` re-entry cooldown — 53 trades over 6 months in the validation, no whipsaw observed. Deferred.
- Pairs retune — 1 trade by design. Deferred.

The Phase 2 exit criteria (WR ≥ 40%, PF > 1.0 on 2+ rule-based strategies) were NOT met. We landed `discovery_momentum` (PF 1.63) and `multi_timeframe` (PF 1.17) above 1.0, but `mean_reversion` is still 0.59 and `momentum` doesn't trade. The next phase is gated on better diagnostics, not more guess-and-check tuning.

### Phase 2.5 — Diagnostics (A1 Sharpe + per-symbol P&L breakdown) — DONE 2026-05-11

**Outcome (post-Phase-2.5 fulltest `fulltest_20260510_234426.txt`)**:
- **Per-symbol P&L breakdown**: shipped. Every strategy section now shows worst-5 + best-5 symbols with P&L, trade count, W/L breakdown.
- **Sim-time fills**: shipped. `PaperBroker.set_current_time` advanced per bar by the strategy runner; fills are timestamped on bar time, not wall clock.
- **Portfolio Sharpe**: now meaningful (came out at **0.91** in the latest run). Computed on cost-basis daily equity, which now spans the simulated period because of the sim-time fix.
- **Per-strategy Sharpe**: suppressed to N/A when noisy (|x|>10 or <20 trading days). Most strategies trip this filter — symptom of the trading-cliff issue below.
- **Mark-to-market open-position equity**: NOT shipped, deliberately. Discovered while implementing it that PaperBroker accepts buys without a cash check, so the open-position book balloons to $4.2M on $100K capital. MTM on those positions produces fantasy equity ($94K → $824K curve). Until the broker grows a cash check, cost-basis is the trustworthy metric.

**Big finding from per-symbol breakdown + sim-time data**: the entire 6-month fulltest is actually 12 days of trading. All 1,298 fills happen between Aug 1-12, 2025; after that, every strategy is wedged against position-value caps. Documented in `AUDIT-2026-05-02.md` C5 and now Phase 2.6 below.

**Mean-reversion diagnostic from per-symbol breakdown**: each closed trade is on a different symbol (~all 51 trades on different names). Not a bad-apple problem. Structural — but tuning is gated on Phase 2.6 because the strategy effectively only ran for 12 days.

### Phase 2.6 — PaperBroker cash check — DONE 2026-05-11

**What landed**: `PaperBroker(initial_cash=...)` tracks cash; buys reject via `InsufficientCashError` (translated to `OrderRejectedError` upstream); sells credit cash. Fulltest orchestrator passes `--capital` through `config.oms.initial_capital` so the broker enforces reality. Live mode unchanged (default `initial_cash=None` = unlimited; live brokers enforce cash themselves).

**Phase 2.6 fulltest result** (`fulltest_20260511_062659.txt`): 54 real fills, 17 closed round-trips, +$94 portfolio P&L. Per-strategy:
| Strategy | Trades | WR | P&L |
|---|---:|---:|---:|
| `discovery_momentum` | 6 | 66.7% | +$270.60 |
| `multi_timeframe` | 10 | 0% | -$150.47 |
| `mean_reversion` | 1 | 0% | -$26.24 |
| `pairs` | 0 | — | $0 |
| `momentum` | 0 | — | $0 |

**The bigger reveal**: the 1,298 fills / 122 trades / "+$57 over 6 months" baseline from Phase 2.5 was 95% phantom. Real result is 54 fills / 17 trades on a SINGLE day (Aug 1). The original "12-day trading cliff" was really a 1-day burst — the prior 11 days of activity were also phantom fills that *would* have been rejected with proper cash accounting.

**The cash check did NOT make strategies trade across more days.** It revealed that:
1. Real rule-based strategies open ~17 positions on Aug 1 and then sit. 8 of those positions stay open the whole 6 months, tying up ~$82K of $100K capital.
2. The strategies don't have edge to close those positions (their exit conditions — RSI > 70, regime flip, upper band — don't trigger on the held names) and don't have cash to open new ones.

So the 12-day cliff became a 1-day cliff, but the underlying issue (strategies don't trade enough to evaluate) got *worse*, because at least the phantom-fill version gave us 122 data points.

### Phase 2.7 — OMS position re-entry fix — DONE 2026-05-12 (commit `08c9224`)

Investigating Phase 2.6's "multi_timeframe 0/10 WR" finding surfaced an OMS
bug, not a strategy logic problem. `_update_position` (`oms/manager.py:288`)
fetched the position row by `(strategy_id, symbol)` regardless of state.
When a strategy closed a position and re-entered the same symbol:

1. New fill landed on the closed row's "Adding to long" branch.
2. `closed_at` was never cleared on the upsert.
3. `BaseStrategy.update_position` popped the position from cache (it
   checked `closed_at is not None`), so the strategy thought it had no
   position.
4. Next bar: strategy re-entered, the OMS pyramided onto the stale row
   again. Result: invisible "ghost" positions — `get_open_positions`
   filtered them out (`closed_at IS NULL AND quantity > 0`), but the
   PaperBroker still deducted cash for them.

AMZN example: 5 buys at 11:06–11:12 after a sell at 10:40 accumulated 205
ghost shares (~$44K). The "0/10 WR" multi_timeframe stat was the first
closed trade per symbol being recorded; everything after that was the
hidden pyramid.

**Fix**:
- `_update_position` treats a closed row (`closed_at is not None` OR
  `quantity == 0`) as a fresh new position era. Resets `side`,
  `quantity`, `avg_entry_price`, `opened_at`, `closed_at`. Carries
  `realized_pnl` forward as cumulative per-strategy-symbol P&L. Fills
  table remains source of truth.
- `PositionRepository.upsert` SQL now includes `side` and `opened_at`
  in `DO UPDATE SET` so re-opens and side flips persist correctly at
  the DB level. The flip case was previously silently failing.

**Regression tests**: `test_update_position_reopen_after_close_same_side`
and `test_update_position_reopen_after_close_opposite_side` in
`tests/unit/test_order_manager.py`. All 30 OrderManager tests pass.

**Effect on the Phase 2.6 numbers**: the prior 6-month run's 17-trade /
+$94 result was correct *for the trades it counted*; it just missed all
the pyramided fills. A post-fix 6-month run on the same period produced
1,110 trades / -$7,258 — exposing the strategies' real P&L, which
Phase 2.8 then validated against IS/OOS.

### Phase 2.8 — Universe narrowing + IS/OOS validation — DONE 2026-05-12 (commit `8ed17f1`)

Two changes shipped together. Plumbing-first scope; no automated parameter
grid yet.

**B — Universe narrowing**: `multi_timeframe`, `mean_reversion`, and
`momentum` had no symbol filter and were trading the 50+ symbols pushed
by the discovery feed. They were designed for the static gateway
universe; `discovery_momentum` and `pairs` self-restrict.

- Added optional `allowed_symbols` config to all three strategies using
  the same pattern `PairsStrategy` uses. Empty / None disables the
  filter. The filter precedes HTF aggregation in `multi_timeframe` and
  `_prev_rsi` writes in `momentum` so out-of-universe state never
  accumulates.
- `FullBacktestOrchestrator._build_isolated_config` injects
  `allowed_symbols = list(self._bt_config.symbols)` for the three
  narrowed types and logs the per-strategy merged config at startup.

**D — IS/OOS validation plumbing**:

- `FullBacktestConfig.strategy_overrides: dict[str, dict]` for per-type
  config patches. Orchestrator applies them after defaults and after
  `allowed_symbols`, so overrides always win.
- `--strategy-overrides PATH` on `run` and `oos` loads a YAML mapping
  `{strategy_type: {key: value, ...}}`. Unknown keys are ignored by
  the strategies' `config.get(...)`.
- New `fulltest oos` subcommand runs `FullBacktestOrchestrator` twice
  (IS then OOS) and emits a side-by-side comparison. DB and Redis
  isolation between the two runs is handled by the existing
  `BacktestInfrastructure.setup()` (truncate + flush on every call) —
  no new DB names needed.
- `src/axtrade/fulltest/comparison.py` (NEW) builds
  `StrategyComparison` + `OOSComparison` from two `FullBacktestResult`s.
  Heuristic verdict: `is_unprofitable` (IS PF < 1 or PnL ≤ 0) →
  `broken` (IS profitable, OOS PF < 1 or PnL < 0) → `degraded` (both
  profitable but OOS PF < 0.75 × IS PF or OOS Sharpe < 0.50 × IS
  Sharpe) → `holds_up`. Text + JSON formatters. Verdicts are
  quick-scan only; underlying metrics are source of truth.

**Tests added** (29 total, all passing):
- `tests/unit/test_strategy_universe.py` — `allowed_symbols` filter on
  each of the 3 strategies, including blocked-symbol HTF/RSI state
  preservation.
- `tests/unit/test_orchestrator_overrides.py` — orchestrator merges
  overrides correctly, injects `allowed_symbols` for the right
  strategy types, leaves discovery_momentum and pairs alone.
- `tests/unit/test_oos_comparison.py` — verdict matrix + formatter
  round-trips.

**Validation runs** (in `data/fulltest_results/`):
- `oos_comparison_20260512_203144.txt` — no-discovery smoke run.
  Confirmed plumbing: narrowed strategies trade only AAPL/MSFT/GOOGL/
  AMZN/NVDA. All 3 strategies show IS_UNPROFITABLE.
- `oos_comparison_20260512_211515.txt` — full discovery-on run, the
  new regression baseline.

**Baseline results (post-Phase 2.8, discovery on):**

| Strategy | IS Trades | IS PF | IS P&L | OOS PF | OOS P&L | Verdict |
|----------|----------:|------:|-------:|-------:|--------:|---------|
| discovery_momentum | 69 | 0.04 | -$148 | 0.56 | -$1,975 | IS_UNPROFITABLE |
| mean_reversion | 78 | **1.29** | **+$714** | 0.27 | -$606 | **BROKEN** |
| multi_timeframe | 613 | 0.24 | -$10,773 | 0.28 | -$5,159 | IS_UNPROFITABLE |
| pairs | 7 | 0.00 | -$253 | 0.01 | -$235 | IS_UNPROFITABLE |

### Phase 3 — Strategy direction (current decision point)

The post-2.8 verdict: **none of the four enabled strategies has
demonstrated a real edge.** Three fail IS; the one that passes IS
(mean_reversion, PF 1.29 +$714 over 12 months) collapses OOS to PF 0.27
— textbook in-sample overfit. The earlier single-period testing was
hiding this because we were tuning and testing on the same 6-month
window.

This is not a tuning problem. PF 0.17 → 0.20 with a parameter tweak
doesn't move the needle. The signals don't have edge. Three branches,
listed in the order to consider them:

**Branch A — Diagnose discovery_momentum's IS/OOS asymmetry** (1–2
sessions). IS PF 0.04 on 69 trades vs OOS PF 0.56 on 485 trades is too
lopsided to be sample variance. Three possible causes:

1. **Bug in scoring** on the 2024-08→2025-08 window. The `DiscoveryService`
   scoring or its inputs may behave differently — e.g., volatility-based
   screeners reading stale data, regime detection trip-points different
   between periods.
2. **Discovery feed composition** drifts sharply. IS year fed different
   symbols than OOS half. If the IS-fed symbols were systematically
   worse trades (low-cap noise rather than momentum names), the IS PF
   reflects the universe, not the strategy.
3. **Real but unstable edge.** The strategy works in some market
   regimes and not others. Possible but the asymmetry feels too large
   to be pure regime.

Action: take the `oos_comparison_20260512_211515.txt` per-symbol
breakdown, look at what IS got fed vs OOS, sanity-check 5 individual
IS trades that lost big. ~1 day of work. If a bug surfaces, the OOS PF
0.56 might be the real number and discovery_momentum becomes a
candidate worth tuning. If no bug, branch A closes and we move to B
or C.

**Branch B — Replace with a research-backed signal** (1–2 weeks). The
B/D plumbing is now ready: any new strategy plugged into the same
`oos` flow gets IS+OOS evaluation immediately. Candidate signals (all
have published evidence on US equities, but most have been arbitraged
down):

- **Overnight reversal** — buy at close, sell at open. Best-documented
  retail-accessible edge; has weakened since 2010s.
- **End-of-day momentum / opening drive** — time-of-day patterns with
  modest published edge.
- **VWAP reversion** intraday — execution-sensitive; harder to test
  honestly without realistic fill modeling.
- **Cross-sectional 12-1 momentum** — works on monthly rebal, requires
  restructuring our 1m-bar pipeline.

Pick one, implement, run through `fulltest oos`. If IS+OOS both clear
PF 1.2+, keep iterating. If not, the answer is "this signal doesn't
work either" and the project's strategy-development experiment is
honest evidence that retail edges on 1-min S&P bars are scarce.

**Branch C — Reframe project as a platform, not a strategy lab**.
Pipeline works, OOS validation works, OMS bugs are now caught. If the
goal is "working trading infrastructure" rather than "profitable bot",
the next work is A3 (IBKR `add_symbols`) + C2 (paper integration test)
+ alert channels + multi-market support. This is the legitimate
choice if branches A and B both fail. The strategies become example
implementations rather than the project's purpose.

**Exit for Phase 3**: a user decision on A/B/C. Each branch has its
own follow-on phases.

### Phase 4 — Cheap cleanup (B1, B2)

Optional but low-cost. Do these any time — orthogonal to strategy work.

- **B2**: delete `src/axtrade/ml/` (966 LoC, hand-rolled GD, disabled in config) and remove `MLPredictionStrategy` from `strategies/__init__.py:24`'s `STRATEGY_TYPES`. Don't replace; revisit if/when we want a real ML layer.
- **B1**: rename `regime` → `trend_regime` in `indicators/regime.py`, `RegimeResult`, and call sites. Honest naming. Bigger blast radius (every call site), so do separately from B2.

**Exit**: tests pass, no broken imports.

### Phase 5 — Expand the data (per user)

User explicitly wants this once Phase 2-3 results look good.

- **Longer window**: combine 2024-08→2025-08 + 2025-08→2026-02 into an 18-month run. Same 5 symbols. Same comparison framework.
- **Wider universe**: run with S&P 1500 instead of S&P 500 (`data/sp1500.csv`). Discovery scans a bigger pool. Throughput needs Phase 1 (batched INSERTs) to be tolerable.
- **Per-symbol breakdown**: extend report to break out P&L per discovered symbol so we can see where the alpha is.

**Exit**: results on the larger windows hold up (no big regression vs. Phase 2 baseline).

### Phase 6 — Paper trading prep (A3, C2)

**Goal**: gate before any live IBKR submission.

- **A3** (`gateway/ibkr.py`): implement `add_symbols` and `remove_symbols` (currently no-op via the base class). Without this, the discovery→trading bridge silently no-ops on IBKR.
- **C2**: write an integration test that hits IBKR's paper TWS — submit a $1 order, verify fill, cancel an open order, reconcile positions. Run from a script, not from production config.
- **Then**: a guarded paper-trading session with one strategy on one symbol. Monitor health endpoints (`/api/health/detailed`). Pull the plug fast if it misbehaves.

**Exit**: paper trading runs unattended for one full session (one trading day) without alerts, with positions reconciling end-of-day.

---

## What this plan deliberately leaves out

- **OOS validation on 2024-08→2025-08**: the data is there, but per user intent we're tuning on the 6-month set first. OOS becomes Phase 5 work, not a Phase 0-3 gate.
- **B3** (`on_tick`/`on_regime_change` hooks), **B4** (multi-market), **B5** (horizontal scaling), **C1** (alert channels), **C3** (paper-broker volume realism), **C4** (rename `axtrade` ↔ `meridian`): all genuinely deferrable. Don't touch until a strategy posts positive expectancy in production paper trading.

---

## Critical files and reused utilities

| File | Phase | What it does |
|------|-------|--------------|
| `ROADMAP.md` | A1 | Top-level priorities — main doc to refresh |
| `docs/strategy-logic-fixes.md` | A2 | Promote "Followups" to live work queue |
| `docs/AUDIT-2026-05-02.md` | A3 | Status notes on A1, C2b |
| `src/axtrade/aggregator/service.py:187` | 1 | Hot path `_process_completed_bar` — buffer + flush here |
| `src/axtrade/common/db.py:288-346` | 1 | `bulk_insert_bars` already exists; reuse, don't reinvent |
| `src/axtrade/fulltest/orchestrator.py:345,350` | 1 | Reference — pre-seed already uses `bulk_insert_bars` |
| `src/axtrade/strategies/momentum.py` | 2 | Relax entry gate (lines 61-77 area) |
| `src/axtrade/strategies/multi_timeframe.py` | 2 | Add re-entry cooldown |
| `src/axtrade/strategies/pairs.py` | 2 | Validate / retune |
| `src/axtrade/fulltest/analytics.py` (`_process_fills`, lines 43-156) | 3 | Mark-to-market equity using bar prices |
| `src/axtrade/fulltest/report.py:267` | 3 | Sharpe display |
| `src/axtrade/indicators/regime.py` | 4 | Rename → `trend_regime` |
| `src/axtrade/ml/` | 4 | Delete |
| `src/axtrade/strategies/__init__.py:24` | 4 | Remove `ml_prediction` from `STRATEGY_TYPES` |
| `src/axtrade/gateway/ibkr.py` | 6 | Implement `add_symbols`/`remove_symbols` |

---

## Verification

End-to-end gates by phase:

- **Phase 0+1**: slow-path fulltest report saved + side-by-side delta vs. pre-rewrite baseline written (Phase 0 deliverable). Then `make test` passes after C2b lands; fulltest with same params completes in <10min and produces matching fills/P&L (Phase 1 deliverable). The slow run is the apples-to-apples baseline; the fast run confirms C2b is behavior-preserving.
- **Phase 2**: each strategy change validated by a fulltest run; commit only if metrics improve or stay flat.
- **Phase 3**: Sharpe in report is non-zero and matches a hand-computed value on a simple two-fill scenario in a unit test.
- **Phase 4**: `make test` passes after rename and `ml/` deletion. Grep for `from axtrade.ml` returns nothing.
- **Phase 5**: 18-month + S&P 1500 run completes; report's per-strategy section breaks out per discovered symbol.
- **Phase 6**: IBKR paper integration test passes against TWS sandbox. One full unattended paper session with no triggered alerts.

Tests exist already (`tests/unit/`, 870 collected, 866 passing per `strategy-logic-fixes.md` line 84). Each phase's code change should land with a unit test added or updated.
