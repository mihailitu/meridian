# Live validation — IBKR S1: data path, market hours (2026-08-04)

First run of the stack against a real TWS (classic TWS 10.49 at `~/tws`,
paper account DUQ887385, delayed market data per D2). Same morning: S0
smoke gate passed (see `ibkr-connection-design.md` status). All four
services via `scripts/start-all.sh ibkr`, config symbols AAPL MSFT GOOGL
AMZN NVDA, every strategy disabled, `discovery.auto_subscribe: false` —
data plumbing only, no order path. Run window 16:34–19:03 EEST; the
measured gate window is 17:57–19:03 (see finding 1 for why).

Pre-market sniff (11:12, positive-signal-only): connect + qualify +
subscribe all clean with zero IBKR error messages; no ticks — ambiguous
outside RTH as pre-committed, not a failure.

## Result: PASS (gate window), with one load-bearing finding

- **Ticks → bars → DB**: on the clean window, counts exact against wall
  clock for all 5 symbols — 66×1m and 13×5m bars per symbol in 66
  minutes; TimescaleDB agrees (65/12 with the final bar in-flight at
  query time). `strategies` consumer group: 752 entries read, 0 pending,
  0 lag.
- **Indicators**: sane on the clean window (AAPL close 306.29 vs SMA20
  306.12, RSI 52.5, BB 305.44–306.80). See finding 3 for the warmup-era
  anomaly.
- **API**: `/api/health/detailed` healthy; discovery scans running at
  cadence (no qualifying scores — expected, auto_subscribe off anyway).
- **Stability**: zero errors/exceptions in all four service logs across
  the full 2.5h run, including the delayed-feed silent period. Clean
  shutdown via `stop-all.sh`.

## Findings

1. **Delayed-feed subscriptions opened pre-open never start streaming**
   (load-bearing). Services started 16:34 EEST: with delayed data the
   effective market clock was 16:19 (pre-open), and 4 of 5 symbols
   produced ZERO ticks for the next 80 minutes — only AAPL, which trades
   actively pre-market, streamed. IBKR itself was fine: a fresh
   diagnostic client (clientId 94) subscribed mid-RTH saw valid delayed
   prices for all 5 immediately, and restarting the gateway at 17:55
   brought all 5 up within seconds (13–21 ticks each in the first 80s).
   Operational rule until fixed: **with delayed data, start the gateway
   after ~16:45 EEST** (delayed clock past the open). Proper fix: a
   silent-symbol watchdog in the adapter (resubscribe symbols with no
   ticks after N minutes) — also valuable for live data. Landed as D6
   (branch `ibkr-silent-watchdog`, see `ibkr-connection-design.md`). The
   adapter's tick handler drops updates with no positive `last`, so
   quote-only pre-open updates are invisible by design.
2. **Stale state across validation runs**: Redis db 0 still held the
   July-19 mock-run streams (and TimescaleDB the mock bars), which made
   raw stream counts misleading during monitoring and may have fed the
   warmup anomaly (finding 3). Validation runbook needs an explicit
   reset step (`reset-paper-trading.sh` and/or stream trim) before each
   run; live consumers were unaffected (`consumer_group_start: "$"`).
3. **Warmup-era indicator anomaly (unresolved, transient)**: ~15 bars
   into the run, AAPL published SMA20=275.41 / BB 164–387 against
   close≈304 — impossible from the clean intraday prices observed.
   Flushed out of the rolling windows by ~20 bars and never recurred.
   Suspected stale-warmup interaction (finding 2) or an early-window
   computation quirk; not root-caused. Re-check on the next run after a
   proper state reset; if it recurs from clean state, investigate the
   IndicatorEngine warmup path.
4. **Ticks are stamped with arrival time** (`datetime.now(UTC)` in the
   adapter), so on delayed data a bar timestamped T contains trades from
   ~T−15min. Fine for plumbing validation; a semantic caveat for any
   strategy-real stage on delayed data (strategy-real needs live
   subscriptions anyway, where the gap collapses).

## Next

- S2 (long soak) wants D4/D5 merged (branch `ibkr-d4-d5`, reviewed,
  1,221 tests green) and ideally the finding-1 watchdog.
- S3 (order path, TWS blotter as independent verifier) is unblocked —
  Read-Only API is already unchecked on the paper login.
- Findings 1–3 above before S2 runs long; finding 4 is a documented
  caveat, not a work item.
