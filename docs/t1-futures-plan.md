# T1 — futures trend following: implementation plan (2026-08-30)

Status: PLAN (draft, not yet adopted). Extends
`docs/research-new-asset-classes.md` (scoping, Phase A authorisation) and is
bound by `docs/research-survey-2026-08.md` §3 (pre-registration amendments)
and informed by `docs/research-shortlist-2026-08-30.md` (deep-research
verdicts). Inherits the standing discipline: offline pandas research first,
binding pre-registration before any frozen run, one tuning pass, one OOS
shot, calibration/replication gates before signal claims. **No signal work
may run before the Phase A gates pass; no IS run before the pre-registration
is frozen; no platform/event-loop work before Phase B passes its gate.**

## Design constraints carried in from the research (fixed, not re-litigated)

1. Signal speeds: lookbacks in the medium+slow zone only (≥ ~3 weeks per the
   survey; the 2026-08-30 evidence says ≤20d signals lost 65–86% of Sharpe
   post-2008 while ~50d lost ~43%). Blend of medium+slow, Baltas–Kosowski
   turnover reduction.
2. Benchmark: vol-targeted long-only portfolio on the same universe — not
   buy-and-hold (Kim/Tse/Wald: vol-scaling is most of published TSMOM alpha).
3. Honest prior: net Sharpe 0.3–0.5, mostly risk premium. No crisis-alpha
   claims in the pre-registration.
4. Contract preference: large-tick contracts where the choice exists (the
   post-2008 trend collapse concentrates in small-tick books).
5. Capital realism: €20–100k. Whole-contract rounding costs ~20% of Sharpe
   at 1-contract positions; breadth via micro contracts beats cleverness on
   few classic contracts. Every backtest cell runs at three account sizes
   (€20k / €50k / €100k) with integer contracts — the unrounded portfolio is
   reported only as a reference line.

## Phase A — data foundation (authorised now; est. 2–4 days)

Deliverable: `data/futures/` (untracked) + hygiene report + cost table +
replication-gate result appended to this doc.

**A1. Source decision (day 1).** Pull WTI crude (contango-heavy, worst case
for roll treatment) from two candidate sources and diff the roll handling:
- candidates: Stooq free continuous series (verify adjustment method),
  Databento CME historical (paid, cheap, individual contracts — lets us build
  and control back-adjustment ourselves), Norgate (retail standard, paid),
  Yahoo splices + our own roll detection (fallback, least trusted).
- decision criterion: we must be able to *prove* the roll treatment (panama /
  back-adjust) rather than trust a vendor label. If a paid source is chosen,
  cost cap for cycle 1: ~€100.

**A2. Universe selection (with A1).** Target 10–20 markets across ≥4 sectors
(equity index, rates, metals, energy, FX futures — spot FX excluded: no
carry). Write the contract-spec table from exchange specs, NOT from memory:
full-size + micro variant per market (MES/MNQ/M2K/MYM, MGC/SIL/MHG, MCL,
M6E/M6A/M6B, rates: micro-yield futures vs full ZN/ZF — margin and notional
verified per contract), tick size, multiplier, margin, and
volatility-normalised tick (for the large-tick preference). The tradeable
subset at each account size falls out of this table.

**A3. Continuous-series builder (tier 1, day 2).**
`src/axtrade/research/futures.py`: back-adjusted continuous daily series from
the chosen source, roll calendar explicit and inspectable. Unit tests
(pytest, same conventions as the repo):
- a synthetic two-contract fixture with a known roll gap → back-adjusted
  series has zero return at the roll;
- panama-adjustment arithmetic (additive) exact on the fixture;
- roll-date detection against a hand-written calendar;
- no look-ahead: series as of date t uses only contracts known active at t.

**A4. Hygiene gates (day 3; all must pass before any signal work).**
1. Roll-gap audit: no daily return attributable to a contract switch, all
   markets, full history.
2. Cross-source spot check on ≥3 markets (≥1 contango-heavy).
3. **Replication gate** (the buy_hold analogue): reproduce the headline
   TSMOM result (12m sign, 1m hold, vol-weighted) on our data in the
   literature's own sample window with the right sign and rough magnitude.
   Failure = dataset or construction is wrong; stop and fix.

**A5. Cost table (with A4).** Per-market half-spread + commission in bp of
notional, from contract specs and IBKR commission schedule — written down
BEFORE the pre-registration, not fitted. Micro contracts pay proportionally
more commission per notional; the table must show micro and full-size
separately.

**Gate A→B:** hygiene report clean + replication gate passed + cost table
frozen. On failure of the replication gate twice (two construction attempts),
T1 pauses and the source decision is revisited.

## Phase B — pre-registered study (est. 3–5 days after Gate A)

**B1. Pre-registration** — `docs/futures-tsmom-preregistration.md` (BINDING,
phase-6 format), frozen before the first run:
- signal: blended medium+slow time-series momentum (exact lookback set and
  blend weights frozen);
- sizing: vol-targeted per market, portfolio vol target frozen, integer
  contracts at the three account sizes, forecast-threshold rule for
  1-contract markets (Carver);
- rebalance: weekly; turnover cap stated;
- costs: the frozen A5 table + a stress cell at 2× costs;
- benchmark: vol-targeted long-only, same universe and vol target;
- primary cell: net Sharpe of the €50k integer-contract portfolio vs the
  long-only benchmark over the IS window;
- IS/OOS split: frozen dates (long history means OOS can be a real multi-year
  block, e.g. last ~4 years held out);
- kill criteria: primary cell below the benchmark, or below 60% of the
  unrounded portfolio's Sharpe (rounding destroyed the edge), or replication
  gate regression;
- one tuning pass on IS, one OOS shot. No second look.

**B2. Backtester (tier 1).** `src/axtrade/research/futures_bt.py`: daily
bars, weekly rebalance, vol targeting, integer contracts, margin check,
cost application from the A5 table. Plain pandas, no asyncio, no event loop.
Unit tests: deterministic P&L on a hand-computable two-market fixture
(the buy_hold analogue for this engine); rounding behaviour; cost
application; margin-breach refusal.

**B3. Run + verdict.** IS run, one tuning pass, OOS shot, verdict appended to
the pre-registration doc and ROADMAP. DBMF/SG Trend as external sanity
benchmarks for the 2019+ overlap (direction, not precision).

**Gate B→C:** OOS verdict PASS per the frozen kill criteria. On FAIL: T1
closes with a written verdict (same as every other strategy), T2 (vol risk
premium) does NOT automatically start — new scoping decision required.

## Phase C — paper trading (only if Gate B passes; est. 3–5 days)

Not an event-loop port. A weekly system needs a **daily batch job**, not
streaming:

- C1. IBKR futures plumbing: contract objects (expiry, multiplier, exchange),
  qualification, and rollover handling in a thin `futures_paper.py` runner —
  gateway/aggregator/strategy-runner stay untouched. Orders via the existing
  `IBKRBroker` path on the PAPER account (DUQ887385) with the standing
  safety rails (live ports refused; no API on live login — futures also
  impossible on the live cash account by design).
- C2. Data: check paper-account futures market-data entitlements; delayed
  data is acceptable for a daily close-based system (decision recorded, not
  assumed).
- C3. Shakedown checklist in the style of
  `docs/live-validation-2026-07-19.md`: order placement, fill accounting
  with multiplier, position reconciliation, roll execution, one full
  simulated roll on paper.
- C4. Run paper for ≥1 quarter with weekly reconciliation vs the backtester's
  expected positions before any further discussion.

## Delegation and effort

- Fable-grade (this session or a fable session): A1 source decision, A3
  back-adjustment design, B1 pre-registration, B3 verdict.
- implementer (sonnet): A2 spec-table assembly, test scaffolding, B2
  backtester boilerplate from the frozen spec, C1 plumbing.
- test-runner (haiku): all suite runs.
- Wall-clock guess: Phase A 2–4 days, Phase B 3–5 days, Phase C 3–5 days —
  strictly serial across gates.

## Out of scope (recorded so nobody drifts)

Live trading; margin account conversion; intraday futures signals; VX/options
(T2 parked); ML anything (gate closed by E4); platform/event-loop futures
support beyond the thin Phase C runner.
