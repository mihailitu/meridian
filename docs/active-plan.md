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

### Phase 2.5 — Diagnostics (A1 Sharpe + per-symbol P&L breakdown)

**Goal**: stop tuning blind. Two concrete report changes that make every future Phase 2 follow-up evidence-based instead of intuition-based.

- **A1 — Mark-to-market Sharpe**: plumb bar prices into `fulltest/analytics.py:_process_fills`. Equity at time `t` = cash + Σ(open_position_size × bar_close_at_t). Bars are in the backtest TimescaleDB so a query during analytics is cheaper than streaming them through. Currently every report shows Sharpe 0.00, which is meaningless.
- **Per-symbol P&L breakdown**: extend the strategy-results section in `report.py` to list trade count + P&L per symbol within each strategy. Today the report says "Symbols: BRO, GOOGL, TRGP..." with no $-figure attached. With this we can see if `mean_reversion` is bleeding evenly across 51 symbols (structural) or losing big on 3-4 specific names (bad-apple).

**Exit**:
- Sharpe is non-zero in two independent runs (within natural noise).
- Per-symbol breakdown landed; `mean_reversion`'s -$306 broken down by symbol.
- Decision recorded: structural fix vs. symbol filter vs. accept and move on.

### Phase 3 — Mean-reversion deep dive (gated on 2.5)

With per-symbol breakdown in hand, decide between:
- **Structural fix**: tighter entry (e.g. require RSI ≤ 30 instead of ≤ 35, or two-bar confirmation at lower band)
- **Symbol filter**: blacklist the worst-performing names from the strategy
- **Volatility gate**: skip RANGING_VOLATILE entries — those moved against us harder

This phase was Phase 4 in the original plan; promoting it now that we know the rest of the rule-based strategies are healthy.

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
