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
  Opt-in only via new `--strategies` flag (excluded from default fulltest runs).
- Hand-compute expected P&L from parquet closes for **one month** (2025-08): sum over symbols
  of `qty × (last_close − first_close)` minus commissions and one entry slippage.
- Run fulltest for that month with ONLY `buy_hold` enabled (`--no-discovery`), ~10 min.

**Gate**: |fulltest P&L − expected| within commissions + slippage tolerance. Pass → iteration
3. Fail → the divergence is the bug; fix inside this iteration before anything else runs.

**Found during execution (2026-06-12)** — the gate did its job; two harness bugs, both fixed
inside this iteration:

- **F6 — report ignored open positions and commissions.** `final_equity` was
  `initial + SUM(realized_pnl)`: unrealized P&L of anything still held at window end simply
  didn't exist (buy_hold would have read $0.00 by construction), and commissions never left
  equity even though they leave PaperBroker cash. Fixed: open positions are marked to their
  symbol's last persisted 1m close (per strategy and overall), and
  `final_equity = initial + realized + unrealized − commissions`. Every prior fulltest report
  understated/overstated any strategy holding positions at the end.
- **F7 — pipeline shutdown truncated the simulation tail.** After the replay producer
  finished, the orchestrator slept a fixed 2s, then stopped the aggregator (and 2s later the
  strategy runner). The producer finishes far ahead of the consumers, so the backlog was
  guillotined: the first calibration run persisted bars only through **Aug 11 of a 31-day
  window (28%)** while reporting "95,409 bars processed" (a replay-side count). Every prior
  fulltest result — including both periods of the IS/OOS comparison — covered an unknown
  prefix of its window, not the window. Fixed: shutdown now drains each Redis consumer group
  (last-delivered-id == last-generated-id, pending 0, with stall detection) before stopping
  services, and the report prints a `Data Through:` coverage line with a loud warning when
  persisted bars stop >4 days before the window end.

Validated against real data: entry fills matched first-bar-close × 1.001 (10 bps slippage) to
the cent; accounting identity `equity = initial + Σqty×(mark − fill) − commissions` holds
exactly against DB fills.

### Iteration 3 — Calibration at scale + metrics sanity ✅ (2026-06-12)

- Same `buy_hold` comparison over the full IS year (~34 min with the drain).
- While it ran: checked the Sharpe annualization in analytics — reported −24/−43 portfolio
  Sharpe is dimensionally implausible (F5 note).

**Gate**: P&L matches arithmetic AND reported Sharpe for buy_hold is plausible (±50% of a
hand-computed value). Both fixable here if not.

**Result**: final equity **$108,595.57 vs hand-computed $108,595.57 — exact**, coverage
through the window's last trading minute (1.13M bars). Metrics required fixes (F8):

- **F8 — analytics were realized-only and trade-gated.** Three compounding artifacts of the
  same cost-basis era: (a) the daily equity curve fed to Sharpe/drawdown was cash-flow-only —
  flat between fills — which is what produced Sharpe −24/−43 (steady small negative steps,
  near-zero variance); (b) `calculate_metrics` short-circuited ALL metrics to 0 when no trades
  closed (buy-and-hold "had" 0% return and 0 drawdown); (c) `compute_analytics` overrode
  total/annualized return with positions-table realized P&L. Fixed: new `mark_to_market_daily`
  curve (cash + open positions at each day's last close, carry-forward across gaps); curve
  metrics computed regardless of trade count; the realized-P&L override now applies only on
  the cost-basis fallback. The old "don't MTM, PaperBroker has no cash check" rationale died
  with Phase 2.6.

Post-fix IS-year buy_hold analytics: total return 8.60%, max drawdown −13.15% (hand: 12.9%),
Sharpe 0.28 — that is the *excess-return* Sharpe (rf=5%/yr baked into `calculate_sharpe`);
raw Sharpe of the same curve is 0.69 vs hand-computed 0.69–0.83. Definitions reconciled,
numbers match. 36 new MTM-curve unit tests.

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

**First pass (2026-06-12)**: scan cadence ✅ (21 scans for 21 trading days), universe
isolation ✅ (non-fed symbols only have day-end-stamped `1d` rows), coverage line ✅ — but
the fed symbols produced **zero** 1m bars and discovery_momentum traded 0 times. Two causes:

- **F9 — the replay producer outran the sim clock.** The producer pushed the entire window
  into Redis in ~1 minute and exited; discovery (correctly on sim time since iteration 1) fed
  50 symbols on sim-day 21, when there was nothing left to replay. In pre-fix history this
  also meant fed symbols joined at the producer's far-future position, not the decision time —
  yet another silent distortion of all old discovery results. Fixed: `ReplayAdapter` takes a
  `throttle` hook; the orchestrator paces the producer to the aggregator consumer-group lag
  (≤20k ticks ≈ 12 s of sim lead), so fed symbols join the replay at the decision time.
- **Structural**: a 1-month window is all warm-up — screeners need 20–25 daily bars, so the
  first discoveries can only happen on the last day or two. The smoke re-runs on a 2-month
  window (≈20 days warm-up + ≈22 active days).

Also noted: `momentum` still traded 0 times in the smoke month even with the fixed config
keys — watch in iteration 5; if it stays at 0 over a year, the regime+cross gates simply
never co-fire and the strategy should be retired with the others.

### Iteration 5 — Honest IS/OOS re-run (closes ROADMAP #1)

Same configuration as `oos_comparison_20260512_211515` (IS 2024-08→2025-08, OOS
2025-08→2026-02, gateway 5, discovery on). ~2 h, background.

**Gate / decision**: discovery_momentum keep-or-kill on its first honest numbers. PF < 1 both
periods → disable it alongside the other four; iteration 6 starts from a clean slate. PF > 1
anywhere → one diagnosis session before touching parameters. Either way, write the verdict
into ROADMAP (per-strategy state table).

**Result (2026-06-13, `oos_comparison` labeled post-harness-fixes)**: **KILL.**

| strategy | IS trades | IS PF | OOS trades | OOS PF |
|---|---|---|---|---|
| discovery_momentum | 1,506 | 0.42 | 6,659 | 0.45 |
| mean_reversion | 319 | 0.40 | 164 | 0.36 |
| multi_timeframe | 3,810 | 0.21 | 1,933 | 0.21 |
| pairs | 12 | 0.06 | 3 | 0.01 |
| momentum | 0 | — | 0 | — |

ROADMAP item #1 is closed: the old 0.04-vs-0.56 IS/OOS asymmetry is gone (0.42 vs 0.45 —
it was the bugs, not regime). discovery_momentum is consistently unprofitable with large
samples in both periods. Note the trade counts vs the broken-era runs (multi_timeframe 3,810
vs 613): the old harness really was processing only a fraction of each window. mean_reversion's
broken-era IS PF 1.29 is now 0.40 — the one "edge" we ever measured was a harness artifact.
The remaining OOS-vs-IS trade-rate difference for discovery_momentum (~9x/day) tracks the
higher-volatility OOS period producing more discoveries — and PF consistency across the
periods says it's regime, not leakage.

**Five for five: every strategy, honestly measured, loses.** The strategy-search phase
question moves to the Option A / Option B fork documented under iteration 6.

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

**IS run #1 (2026-06-12, threshold −1%)**: FAIL. 284 trades, WR 45.4%, PF 0.50, −$8,136.
Avg loser $112 vs avg winner $67 — megacap intraday losers kept falling overnight. Gross edge
≈ −30 bps/trade before costs, so not cost drag: the naive version of the signal is negative
on these five names in this window. No symbol was profitable (best: GOOGL −$216).

**Tuning pass (the one allowed)**: threshold −1% → −2%, via `--strategy-overrides`. Rationale:
documented reversal strength increases with drop magnitude; restricting to extreme
dislocations is the highest-prior single change. If this also fails IS, the signal is swapped
for 12-1 momentum per the gate — no second tweak.

**IS run #2 (threshold −2%)**: FAIL. 127 trades, WR 53.5%, PF 0.63, −$2,479. Better in the
expected direction (magnitude helps) but the loser/winner asymmetry persists ($124 vs $67).
**Verdict: overnight reversal on the gateway 5 is dead.** No further tuning.

**Structural finding before invoking the swap clause**: the backup (cross-sectional 12-1
momentum) collides with F4 head-on. Every remaining documented daily-horizon anomaly is
cross-sectional over a broad universe — and our universe data is survivorship-biased
(downloaded from today's index membership; 2024's delisted losers don't exist on disk). A
long-the-winners strategy tested on a winners-only universe produces an upper bound, not a
verdict: PF < 1 would still falsify, but PF > 1 could NOT graduate. Additionally, 12-month
formation windows don't fit inside the test windows (no pre-window data on disk for the IS
start; the OOS window is only 6 months), so honest cross-sectional momentum also needs
(a) pre-window daily seeding from the adjacent period file where it exists, and (b) a
point-in-time membership source (Wikipedia's S&P constituent-change history can approximately
reconstruct it) or delisting-inclusive data. Decision on whether to invest in that data work
vs. calling the strategy-search phase concluded is deferred to after iteration 5's verdict.

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
