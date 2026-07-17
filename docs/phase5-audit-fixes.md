# Phase 5: Audit fixes

> Executes the chop order from [`AUDIT-2026-07-12.md`](AUDIT-2026-07-12.md) (whole-project
> audit after phase 4). Branch `phase5-audit-fixes`, branched off `main` at the phase-4
> merge. Same execution model as phases 3-4: small gated iterations, one commit each,
> implementation delegated with written specs, every diff reviewed and independently
> test-verified before commit.

## Iterations

| # | Iteration | Audit items | Status |
|---|-----------|-------------|--------|
| 1 | API lockdown | P0-5, P1-7 | **DONE** (39589be — 127.0.0.1 bind, X-API-Key dep on 7 mutating routes, AXTRADE_API_KEY env override, gateway preference in-memory) |
| 2a | Data-layer code fixes | P0-1, P0-2, P0-3 | **DONE** (9593fae — Adjustment.SPLIT, non-overlapping chunks, dedup, gap sanity warning, skip-symbol-on-chunk-failure, --force flag; window-aware manifest selection + per-symbol monotonic replay guard) |
| 2b | Adjusted re-download + IS/OOS re-run | P0-1/2/3 validation | **DONE** (2026-07-14 — re-download complete: 1,445 files, all 16 skips explained; sanity pass clean: TSCO split gapless, 3 suspect gaps all same-day bad prints, zero dup timestamps; buy_hold calibration gate **exact to the cent** ($108,595.57, full coverage); `post-data-fixes` IS/OOS re-run (`oos_comparison_20260714_162449.txt`) re-certified the verdict table — no verdict flipped, discovery_momentum's legs now structurally comparable (P0-3 confirmed fixed). Raw backup deleted after validation. Findings: discovery-enabled fulltests now ~1 sim-month/hour on clean data (IS/OOS pair ~18h); reported Sharpe embeds a hardcoded 5% risk-free rate (`backtest/analytics.py`) — labeling folded into P1-11) |
| 3 | Live-path OMS | P1-1, P1-2, P1-4 | **DONE** (d5084e7 — fill routing to strategies, pending-open caps, conditional SUBMITTED stamp, fill lock, cancel propagation + cancel_order; review caught a pending-marker wipe in the post-submit poll, regression-tested) |
| 4 | IBKR tick path | P0-4 | **DONE** (99c7d4d — int(float(volume)) + poison-message acks, cumulative→delta bar volume, ib.sleep(0) removed; live-TWS validation still owed) |
| 5 | Live-paper pre-flight | P1-5, P1-6, P1-8 | **DONE** (c1353cc — one-sided quote skip, initdb migrations hook, stream maxlen + consumer-group start knob; integration test re-verified) |
| 6 | Cross-process discovery bridge + eviction orphans | P1-3, P1-9 | **DONE** — discovery scanning moved from the API process to the strategy runner (matching fulltest wiring); API is now a DB reader (`DiscoveryRepository` / `discovered_symbols`) + command publisher (`axtrade:discovery:control`, 202-ack endpoints); manual add/clear persist immediately via `persist_discovered()`. Eviction guard: stale-but-held symbols keep their subscription; on position-check failure evict nothing (fail safe). Review caught a control-loop busy-spin on subscription close that OOM-froze the workstation mid-iteration (20+ GB via mock call-history growth) — fixed with a resubscribe backoff |
| 7 | pairs wedge | P1-10 | **DONE** — `_spread_direction` deleted; spread state now derived from the actual position (only long-symbol_a spreads exist, so a held position fully determines direction). Rejected entries re-fire, rejected closes retry next bar, restart-restore reaches the z-score exit; duplicate in-flight entries suppressed via new `BaseStrategy.has_pending_open()`. 4 regression tests. No re-run: verdict stays DEAD (it traded identically to the penny pre/post data fixes; the wedge explains the tiny trade count, not the losses) |
| 8+ | Next: P1-11 (dashboard money numbers + Sharpe-definition labeling: `backtest/analytics.py::calculate_sharpe` silently subtracts a 5% risk-free rate while `analytics/metrics.py` defaults to 0 — unify or label), then P2 tier | | not started |

Suite: 1098 unit tests green as of iteration 7 (987 at branch start); `make test-integration`
passes (re-verified after iteration 6 — the paper pipeline now hosts the discovery scanner
in the strategy-runner process).

## Ongoing download (iteration 2b) — state as of 2026-07-12 ~13:30

A full adjusted re-download of the S&P 1500 universe is running **on the original
workstation** (started 2026-07-12 08:46, ETA ~06:30 next morning). It survives the Claude
session — `nohup`, detached.

- **Command**: `.venv/bin/python -m axtrade.fulltest download --start 2024-08-01 --end 2026-02-01 --universe sp1500`
  (single continuous 18-month range → **one parquet file per symbol**, which removes the
  two-file-per-symbol manifest ambiguity of the old layout entirely)
- **Output**: fresh `data/historical/` (split-adjusted, deduped). The old
  raw/duplicated data was moved intact to `data/historical_raw_backup/` (~6.3 GB — keep
  until the re-run is validated, then deletable)
- **Log**: `/tmp/claude-1000/-home-mihai-workspace-meridian/ee91f2f6-4a81-486c-859a-2b5657d3de65/scratchpad/download.log`
  (restarted 2026-07-12 ~18:04 after a machine crash killed the first run at 602 symbols;
  the manifest resumed cleanly)
- **Progress check**: `grep -c "Symbol complete" <log>`; or
  `ls data/historical/*.parquet | wc -l` (604/~1,440 at 18:10 restart)
- **If it dies**: re-run the same command — the manifest resumes (completed symbols are
  skipped; do NOT pass `--force`)
- **Known skips (expected, correct)**: BF-B, BRK-B (Alpaca wants dot notation — dash→dot
  ticker mapping is on the follow-up list); ATVI, CDAY (delisted/renamed, no data in
  window). Suspect-gap warnings for AAT (2025-04-21) and BR (2024-08-05) were investigated:
  both are bad thin extended-hours prints that snap back same-day, NOT unadjusted splits —
  more ammo for the P2-2 RTH-filter decision
- **Verified on early files**: unique timestamps (old files were ~33% duplicate rows),
  day-boundary ratios clean, ~46-55s/symbol

### After the download completes — execution plan (written 2026-07-12 evening)

> **Executed 2026-07-13/14 — all gates passed.** Download finished 07-13 07:40 (13.5h
> across two sessions bridging a machine crash). Steps 0–2 ran automatically off a
> scheduled check; step 3 launched on go-ahead 07-13 22:28 and finished 07-14 16:24
> (~18h — see the wall-clock note in iteration 2b). Results recorded in the iteration
> table above and the ROADMAP verdict table.

Framing: this is a **re-audit of the verdict table, not a formality**. Every prior number
was measured on data with ~33% duplicate rows and (for the discovery universe) unadjusted
splits, and those distortions have no known direction — any verdict may flip, including
"every strategy loses". Verdicts flip on evidence, not on re-tuning: the IS/OOS gate
discipline holds (re-measuring existing hypotheses on corrected data does not burn the
single OOS shot; reacting to the new OOS numbers with another tuning pass would).

**Step 0 — completion check (~2 min).** Log tail reports completion;
`ls data/historical/*.parquet | wc -l` ≈ 1,440 (1,447-symbol universe minus known skips:
BF-B, BRK-B, ATVI, CDAY). Grep the log for symbol failures beyond those; a handful more
delisted tickers is acceptable, a systematic failure pattern is not.

**Step 1 — data sanity pass (~15 min).**
1. TSCO around 2024-12-20 (5:1 split): adjusted data must show no day-boundary gap.
2. Collect every suspect-gap warning from the log; classify each as same-day snap-back
   (bad thin print, acceptable — AAT 2025-04-21 and BR 2024-08-05 already confirmed as
   this) vs persistent level shift (missed split — **stop and investigate before
   proceeding**).
3. Sample ~20 files: timestamps unique and monotonic (old files were ~33% duplicates).
4. Confirm files span the full 2024-08-01→2026-02-01 range (one file per symbol — the
   two-file layout and its manifest ambiguity are gone).

**Step 2 — buy_hold calibration gate (~40 min).** The phase-3 hand-computed target
($108,595.57) is stale: deduped data changes fills and marks. Recompute by hand from the
NEW parquet (recipe in docs/phase3-trustworthy-harness.md iterations 2-3: entry fill =
first 1m bar close × 1.001, `final_equity = initial + Σqty×(mark − fill) − commissions`),
then run

```
python -m axtrade.fulltest run --start 2024-08-01 --end 2025-08-01 \
    --symbols AAPL MSFT GOOGL AMZN NVDA --capital 100000 --strategies buy_hold
```

**Gate: match to the cent, coverage through the window's last trading minute.** A mismatch
means the phase-5 data fixes regressed the harness — stop; do not spend 4h on step 3.

**Step 3 — IS/OOS re-certification (~4 h).**

```
python -m axtrade.fulltest oos --is-start 2024-08-01 --is-end 2025-08-01 \
    --oos-start 2025-08-01 --oos-end 2026-02-01 \
    --symbols AAPL MSFT GOOGL AMZN NVDA --capital 100000 \
    --strategies momentum mean_reversion multi_timeframe pairs discovery_momentum overnight_reversal \
    --label post-data-fixes
```

Notes: `overnight_reversal` is included explicitly (excluded by default) so its failed-IS
verdict gets re-measured on clean data — with its already-tuned params, its one tuning
pass is spent. No `--strategy-overrides`: same hypotheses, corrected data. Expected
sensitivity: the five static-symbol strategies had no in-window splits (dedup + replay
ordering are the only changes — verdicts expected to survive, numbers will shift);
discovery_momentum is effectively measured for the first time (P0-3 made its old IS/OOS
structurally incomparable, and its universe DID contain in-window splits).

**Step 4 — record and close out.**
1. Update the ROADMAP per-strategy table with the `post-data-fixes` numbers; remove the
   "under re-certification" flag; explicitly note any verdict flip vs the
   `post-harness-fixes` run and attribute it (duplicates / split artifacts / replay
   ordering).
2. Close iteration 2b in the table above (reference the comparison report filename in
   `data/fulltest_results/`).
3. Delete `data/historical_raw_backup/` (~6.3 GB) — only after steps 1–3 all pass.
4. Commit the doc/ROADMAP updates as the iteration-2b close-out.

Total wall clock ≈ 5 h. Steps 0–2 are cheap and gate the expensive step 3; anything
anomalous in 0–2 stops the plan.

## Context for pickup on another machine

The download artifacts (`data/historical/`, untracked) exist only on the original
workstation, so the IS/OOS re-run must happen there (or after copying the data). All code
fixes are on `origin/phase5-audit-fixes`. `main` is at the phase-4 merge and pushed. The
API/OMS/gateway iterations (1, 3, 4, 5) are fully independent of the download and already
verified; remaining audit work (P1-3/9/10/11, P2 tier) can proceed from any machine.
