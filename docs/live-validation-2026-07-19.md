# Live validation — part 1: full-stack mock shakedown (2026-07-19)

First-ever run of the stack as real separate services (ROADMAP #3, first
half). Sunday evening, market closed → mock adapter; the Alpaca market-day
session is part 2. ~70 minutes, all four services via `scripts/start-all.sh
mock` (adapter arg added for this), real Redis + TimescaleDB, paper state
reset first. Temporary config for the run (reverted after): 
`discovery_momentum.enabled: true`, `discovery.auto_subscribe: true`.

## Result: PASS

- **Ticks → bars → DB**: counts exact against wall clock the whole run
  (58×1m + 12×5m bars per symbol over 58 minutes; Redis streams and DB
  agree). Aggregator consumer lag 0 throughout.
- **Indicators**: NULL during warmup, then present from exactly bar 15
  (RSI-14) and bar 20 (SMA-20) — warmup arithmetic exact.
- **Regime detection**: live and correct via `/api/regime/current`
  (own table; see finding 3).
- **Discovery**: 12 scans at the 300s cadence; first genuine screener
  match (GOOGL momentum, RSI 70.2) recorded and served by the API.
  Composite score −0.73 < min_score 60 → correctly no auto-subscribe, no
  trade. Mock random-walk never produces qualifying scores, so the
  order path and the discovery→gateway bridge were NOT exercised — that
  is part 2 / S3-IBKR territory, not a defect.
- **Stability**: zero errors in all four service logs; RSS flat
  (45–75 MB/service); staleness watchdog quiet; clean shutdown.

## Findings

1. **`/api/gateway/status` reports config, not runtime** — showed
   `current_adapter: "alpaca"` while the gateway ran mock (CLI override
   invisible to the API service). Dashboard can't be trusted about the
   adapter during an unattended run until fixed. Fix idea: gateway
   publishes its actual adapter (Redis key or control-channel echo) and
   the API reads that.
2. **Discovery `discovered_at` timestamps 3h off** — API returned
   `12:39:06+00:00` for a scan that ran 15:39 UTC: a naive-datetime
   double conversion (UTC value treated as local EEST and converted
   again) somewhere in the discovery persistence/serialization path.
3. **`bars.regime` column is vestigial** — never populated; regime lives
   in its own table. Cleanup candidate (drop column or populate), not a
   bug.

## Part 2 (pending): Alpaca market-day session

Next US session: same procedure with `start-all.sh alpaca` — reset paper
state, re-flip the two temp config keys, run through the session, check
dashboard/DB against expectations, then revert flips. Watch specifically:
finding 1 (adapter display), IEX-feed tick rates vs the staleness
watchdog, and whether real data produces discovery scores ≥ 60 (bridge +
order path). IBKR track (S0+) proceeds separately once the paper account
is approved — see `docs/ibkr-connection-design.md`.
