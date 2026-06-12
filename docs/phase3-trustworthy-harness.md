# Phase 3: Trustworthy harness, then a real edge

> Findings from the 2026-06-12 design/implementation review, and the iterative plan that
> follows from them. Supersedes the "tune the existing strategies" framing. ROADMAP item #1
> (discovery IS/OOS asymmetry) is diagnosed below — it was bugs, not regime.
>
> **Execution model**: small iterations, each ending at a committable state with explicit
> evidence and a go/no-go gate. Cheap smoke runs gate expensive full runs; full runs gate
> strategy work. Nothing burns 2h of replay before a 10-minute version has proven the
> mechanics.

## Findings

### F1 — Discovery scores the universe on future data (CRITICAL)

`_preseed_universe_bars` (`src/axtrade/fulltest/orchestrator.py:~296-303`) filters each parquet
file to the backtest window, then keeps `df.tail(bar_limit)` — the **last 50 bars of the
window** — and inserts them before replay starts. Discovery fetches bars with
`ORDER BY time DESC LIMIT 50` and no time bound (`common/db.py:140-146`), so **every scan for
the entire run scores the universe on end-of-period prices**. The IS run picked symbols that
were hot in July 2025 while trading August 2024.

This is the root cause of the discovery_momentum IS/OOS asymmetry (69 vs 485 trades): each
period's discoveries are determined by which symbols happened to look good in the *final* 50
minutes of that period, not by anything the strategy could have known.

### F2 — Discovery score cache is a sticky maximum (CRITICAL)

`DiscoveryService._update_discovered` (`discovery/service.py:199-206`) only replaces a cached
entry when the new |score| is higher. Scores never decrease, nothing expires, and
`clear_discovered()` is never called during a backtest. Consequences:

- Once a symbol ever crosses `min_score: 60` it is permanently tradeable.
- The `score_decay_exit: 30` exit in `discovery_momentum` is effectively dead code.
- `_feed_gateway`'s stale-symbol removal never fires (the discovered set never shrinks).

**F1 + F2 together invalidate every discovery_momentum backtest number produced so far,
including the "OOS PF 0.56" that looked like the only edge.**

### F3 — Momentum strategy ignores its config (HIGH)

`momentum.py:31` reads `rsi_cross_level` (default 50); `config/default.yaml:89` supplies
`rsi_oversold: 30`, which nothing reads. Tuning that key did nothing; momentum produced 0
trades in both IS and OOS (absent from the comparison report entirely).

### F4 — Survivorship + look-ahead universe (MEDIUM, deferred)

`SP500SymbolProvider`/`SP1500SymbolProvider` fetch *today's* Wikipedia membership and apply it
retroactively; `data/historical/` was downloaded from that list, so 2024's delisted losers
don't exist in our data at all. Flatters any long strategy on the broad universe. A real fix
needs point-in-time membership data; for now we document the bias and keep universe-wide
results out of go/no-go decisions.

### F5 — Design-level: no edge exists at this horizon (the deeper problem)

Indicator-cross strategies on 1-minute bars of mega-cap US equities compete with colocated
HFT. Observed numbers match "zero-edge signal paying tolls": multi_timeframe lost ~$17.5/trade
≈ exactly the simulated round-trip cost (10 bps slippage × 2 + commission ≈ 22 bps on a ~$8k
position). Its 14% WR against a 2%/3% stop/target (breakeven = 40%) is unwinnable at any
parameter setting. mean_reversion is the only horizon-coherent strategy and it still collapsed
OOS (PF 1.29 → 0.27). Conclusion: **change the trading horizon, not the indicators.** New
strategies target daily/overnight effects where documented anomalies exist and a ~20 bps cost
is amortized over 1–5% moves.

Secondary realism notes (matter once something works, not why we lose): fills at signal-bar
close (mild look-ahead); no bid-ask spread but 10 bps/side slippage is pessimistic for
mega-caps; no intrabar stop triggering; multi_timeframe HTF buffer = 3.3h (can't see a daily
trend); reported Sharpe of −24/−43 is dimensionally implausible — metrics annualization worth
a look while we're in there.

## Iterations

| # | Iteration | Cost | Gate that ends it | Status |
|---|-----------|------|-------------------|--------|
| 1 | Harness fixes (F1–F3) + unit tests | code only | full test suite green | **DONE** (branch `phase3-harness-fixes`) |
| 2 | Calibration: `buy_hold` strategy + 1-month smoke | ~10 min run | fulltest P&L ≈ hand-computed within costs | next up |
| 3 | Calibration: full IS-year run | ~1 h run | same check at scale; Sharpe/metrics sanity | gated on 2 |
| 4 | Discovery smoke: 1-month run, discovery on | ~10 min run | scans daily, scores decay, no future bars visible | can run parallel to 3 |
| 5 | Honest IS/OOS re-run (closes ROADMAP #1) | ~2 h run | discovery_momentum keep/kill verdict | gated on 3+4 |
| 6 | Overnight reversal: implement + IS run | code + ~1 h | IS PF > 1 with ≥50 trades, else iterate/swap signal | gated on 3 |
| 7 | Overnight reversal: single OOS shot | ~40 min run | OOS PF > 1 with ≥50 trades → graduate | gated on 6 |
| 8 | Wrap-up: ROADMAP refresh, archive this plan | docs only | — | last |

Each iteration is one commit (or a small stack). If a gate fails, the fix happens inside that
iteration — the next one never starts on top of an unexplained result.

### Iteration 1 — Harness fixes ✅ (implemented 2026-06-12)

**1a Sim-time-aware discovery on daily universe bars** (fixes F1)

- `BarRepository.get_bars` gained optional `end_time` (`AND time <= $4`).
- `DiscoveryService.scan` gained optional `as_of`, threaded into `_fetch_bars_data`. Live mode
  passes `None` (behavior unchanged).
- Aggregator's `on_bar_callback` passes the completed bar's timestamp;
  `BacktestDiscoveryRunner.on_bar(bar_time)` forwards it as `as_of`.
- Pre-seed rewrite (`daily_rows_from_minute_df`): each symbol's 1m parquet aggregates to
  **daily bars** over the full window (timestamp = last 1m bar of the day, so a day's bar only
  becomes visible *after* its close), inserted with `interval='1d'`. Full window, not tail —
  ~375k rows for the IS year vs 150M if we seeded 1m. Fulltest overrides discovery to
  `interval: '1d'`, `bar_limit: 50`.
- `BacktestDiscoveryRunner` scans once per sim *day* (daily data → intraday re-scans would see
  identical data; saves ~1000 pointless 1500-symbol query rounds). `--discovery-interval`
  (bars) CLI knob removed.
- Known warm-up: screeners need 20–25 daily bars, so discovery is silent for the first ~5
  weeks of each window. Both IS and OOS pay it equally; no pre-window data exists for the IS
  start anyway.

**1b Cache rebuilds per scan** (fixes F2)

- `scan()` rebuilds `_discovered` from the current scan's results (max |score| per symbol
  *across screeners within the scan*; `source='manual'` entries preserved; a scan where every
  screener errored keeps the previous cache — no information ≠ nothing qualifies).
- `score_decay_exit` is now live; live-mode `_feed_gateway` stale removal now fires.
- Backtest-specific: `BacktestDiscoveryRunner` does **not** remove stale symbols from the
  replay gateway — if replay stops, the strategy never gets the bar that would trigger its
  exit, stranding positions. Keep replaying everything ever added; the strategy exits on score
  decay naturally.

**1c Momentum config key** (fixes F3): `default.yaml` momentum block switched to the keys the
code reads (`rsi_cross_level`, `trend_strength_min`).

**Evidence**: 27 new unit tests (runner cadence / `as_of` threading / monotonic sim clock /
no-stale-removal / daily aggregation), 6 rewritten cache-semantics tests, full suite 934
passed (4 failures pre-exist on main: 3× `test_alerts.py` event-loop pattern, 1×
`test_oms_broker.py` — tracked, not ours). Smoke-tested aggregation on real AAPL parquet:
227k minute rows → 271 daily rows, day-end timestamps, indicators correct after warm-up.

### Iteration 2 — Calibration smoke (can the harness measure a known result?)

We currently cannot distinguish "strategy has no edge" from "simulator eats the edge". Fix
that before any strategy work.

- Implement trivial `buy_hold` strategy: buy each allowed symbol once on its first bar, never
  exit. ~40 LoC + registration; `allowed_symbols` = gateway 5; no discovery dependency.
- Hand-compute expected P&L from parquet closes for **one month** (2025-08): sum over symbols
  of `qty × (last_close − first_close)` minus commissions and one entry slippage.
- Run fulltest for that month with ONLY `buy_hold` enabled (`--no-discovery`), ~10 min.

**Gate**: |fulltest P&L − expected| within commissions + slippage tolerance. Pass → iteration
3. Fail → the divergence is the bug; fix inside this iteration before anything else runs.

### Iteration 3 — Calibration at scale + metrics sanity

- Same `buy_hold` comparison over the full IS year (~1 h, background).
- While it runs: check the Sharpe annualization in `analytics/` — reported −24/−43 portfolio
  Sharpe is dimensionally implausible (F5 note); buy-and-hold over a year gives a known-order
  benchmark to validate against.

**Gate**: P&L matches arithmetic AND reported Sharpe for buy_hold is plausible (±50% of a
hand-computed value). Both fixable here if not.

### Iteration 4 — Discovery smoke (mechanics, not P&L)

One month, discovery ON, default strategies (~10 min; can run alongside iteration 3).
Verify from logs/DB, not vibes:

- scan count ≈ trading days in the window (daily cadence works);
- a sampled symbol's score *changes* across scans, and symbols drop out (cache rebuild works);
- bars table contains only `1d` rows for non-gateway symbols, and no query returned a bar
  newer than its scan's `as_of` (spot-check via log timestamps);
- discovery_momentum trade count is sane (entries follow score≥60 days, exits include
  score-decay exits).

**Gate**: all four observed. Then — and only then — spend 2 h on iteration 5.

### Iteration 5 — Honest IS/OOS re-run (closes ROADMAP #1)

Same configuration as `oos_comparison_20260512_211515` (IS 2024-08→2025-08, OOS
2025-08→2026-02, gateway 5, discovery on). ~2 h, background.

**Gate / decision**: discovery_momentum keep-or-kill on its first honest numbers. PF < 1 both
periods → disable it alongside the other four; iteration 6 starts from a clean slate. PF > 1
anywhere → one diagnosis session before touching parameters. Either way, write the verdict
into ROADMAP (per-strategy state table).

### Iteration 6 — Overnight reversal: implement + IS run

Buy the day's biggest intraday losers shortly before the close, exit at next open
(close-to-open reversal effect; persists because it requires overnight risk intraday players
won't hold). One decision/day, fits the existing 1m pipeline (compute intraday return from
bars, enter on the ~15:50 ET bar, exit on the open bar).

- Implement + unit tests (entry window, loser ranking, next-open exit, no re-entry same day).
- `allowed_symbols` = gateway 5 to start; all other strategies disabled.
- One fulltest IS-year run (~1 h). One tuning pass allowed on IS only (threshold, N losers).

**Gate**: IS PF > 1 with ≥50 trades → iteration 7. Fail after one tuning pass → swap signal
(backup: cross-sectional 12-1 momentum, monthly rebalance — lowest cost sensitivity, most
robust documented anomaly, data on disk, F4 caveat applies) and repeat this iteration once.

### Iteration 7 — Overnight reversal: single OOS shot

One OOS run (2025-08→2026-02), no parameter changes after seeing results.

**Gate (graduation)**: OOS PF > 1 with ≥50 trades. Pass → widen to a liquid universe subset as
a follow-up phase. Fail → record it honestly in ROADMAP; the platform-pivot branch (ROADMAP
#3) becomes the recommended path.

### Iteration 8 — Wrap-up

ROADMAP refresh (per-strategy table, what's next), archive this doc to `docs/iterations/` per
repo convention, fold harness-behavior notes into CLAUDE.md if anything changed for operators.

### Explicitly not doing

- Tuning mean_reversion further (OOS already gave the verdict).
- Evaluating discovery_momentum before 3.1 lands.
- Real survivorship fix (needs point-in-time membership data; tracked as F4).
- `ml/` deletion stays on ROADMAP as B2 — orthogonal, cheap, anyone can pick it up.
