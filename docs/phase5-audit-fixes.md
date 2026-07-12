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
| 2b | Adjusted re-download + IS/OOS re-run | P0-1/2/3 validation | **IN PROGRESS** — see "Ongoing download" below |
| 3 | Live-path OMS | P1-1, P1-2, P1-4 | **DONE** (d5084e7 — fill routing to strategies, pending-open caps, conditional SUBMITTED stamp, fill lock, cancel propagation + cancel_order; review caught a pending-marker wipe in the post-submit poll, regression-tested) |
| 4 | IBKR tick path | P0-4 | **DONE** (99c7d4d — int(float(volume)) + poison-message acks, cumulative→delta bar volume, ib.sleep(0) removed; live-TWS validation still owed) |
| 5 | Live-paper pre-flight | P1-5, P1-6, P1-8 | **DONE** (c1353cc — one-sided quote skip, initdb migrations hook, stream maxlen + consumer-group start knob; integration test re-verified) |
| 6 | Cross-process discovery bridge + eviction orphans | P1-3, P1-9 | **DONE** — discovery scanning moved from the API process to the strategy runner (matching fulltest wiring); API is now a DB reader (`DiscoveryRepository` / `discovered_symbols`) + command publisher (`axtrade:discovery:control`, 202-ack endpoints); manual add/clear persist immediately via `persist_discovered()`. Eviction guard: stale-but-held symbols keep their subscription; on position-check failure evict nothing (fail safe). Review caught a control-loop busy-spin on subscription close that OOM-froze the workstation mid-iteration (20+ GB via mock call-history growth) — fixed with a resubscribe backoff |
| 7+ | Next: P1-10 (pairs wedge), P1-11 (dashboard money numbers), then P2 tier | | not started |

Suite: 1094 unit tests green as of iteration 6 (987 at branch start); `make test-integration`
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

### After the download completes

1. Sanity pass: file count ~1,440; spot-check TSCO around 2024-12-20 (its 5:1 split must
   show no gap in adjusted data); scan the log's suspect-gap warnings for any
   persistent-level shift (real missed split) as opposed to same-day snap-backs.
2. IS/OOS re-run to re-certify the per-strategy verdict table (the audit invalidated the
   discovery_momentum row — IS and OOS were structurally different experiments under P0-3):

   ```
   python -m axtrade.fulltest oos --is-start 2024-08-01 --is-end 2025-08-01 \
       --oos-start 2025-08-01 --oos-end 2026-02-01 \
       --symbols AAPL MSFT GOOGL AMZN NVDA --capital 100000
   ```

   Label the result `post-data-fixes`. Expect ~4h wall clock.
3. Update the ROADMAP per-strategy table with the new numbers and close iteration 2b in
   this doc.

## Context for pickup on another machine

The download artifacts (`data/historical/`, untracked) exist only on the original
workstation, so the IS/OOS re-run must happen there (or after copying the data). All code
fixes are on `origin/phase5-audit-fixes`. `main` is at the phase-4 merge and pushed. The
API/OMS/gateway iterations (1, 3, 4, 5) are fully independent of the download and already
verified; remaining audit work (P1-3/9/10/11, P2 tier) can proceed from any machine.
