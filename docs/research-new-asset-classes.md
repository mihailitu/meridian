# New-asset-class research — scoping (2026-08-29)

Status: SCOPING. Nothing here is pre-registered; no IS run may happen off this
document.

> **2026-08-29 (same day, later):** the four-thread deep-research survey
> (`docs/research-survey-2026-08.md`) confirmed T1 as the top-ranked thread
> and AMENDED its Phase B pre-registration requirements (vol-targeted
> long-only benchmark, lookbacks ≥ ~3 weeks / medium+slow blend, net Sharpe
> 0.3–0.5 prior) — see §3 there. It also added two cheap pre-registered
> micro-experiments (pre-FOMC window, last-half-hour momentum) alongside
> Phase A, and closed the sub-15-minute horizon question with four
> independent lines of evidence. It exists to pick ONE thread and define what its Phase A (data) must
prove before a pre-registration is even drafted.

Relationship to the stopping rule: this track is on **new data and new
instruments**, outside the phase-7 rule ("if the F1 retest dies, strategy
research **on this dataset** closes"). It does not reopen the 1m/daily S&P
work, and it inherits the same discipline: offline pandas research first
(phase-6 pattern), binding pre-registration before any frozen run, one tuning
pass, one OOS shot, calibration/replication gates before signal claims. No
event-loop or platform work until a strategy earns it.

## Why leave equities (recap of the evidence)

The closed tracks died on one number: on 1m equity data measured gross alpha
was ~1–2bp/trade against a 3–5bp/side cost floor, and the one real daily
signal (F1, IC t=+3.1) needed ~8.5bp/day to clear a 10bp/day round-trip cost
(`docs/DIAGNOSTICS-2026-07-18.md`, `docs/phase6-cross-sectional.md`). The
lesson is structural: the ratio of expected gross move per position to
round-trip cost must be large. That points to (a) lower-friction instruments
and/or (b) longer horizons — not to better signals at the same horizon.

## Candidate threads

### T1 — Time-series momentum / trend following on liquid futures (daily)

- **Idea**: sign-of-past-return (or breakout) per market, 1–12 month
  lookbacks, volatility-targeted sizing, diversified across equity index,
  bond, FX, metals, energy futures. Rebalance weekly/monthly.
- **Evidence base**: the best-documented anomaly that survives publication —
  Moskowitz/Ooi/Pedersen (2012) "Time Series Momentum" and a century-long
  literature (Hurst/Ooi/Pedersen "A Century of Evidence on Trend-Following").
  Honest caveat: public trend indices (SG Trend) were roughly flat 2010–2019
  and paid off in 2022; the premium is real but lumpy and decayed vs pre-2010.
- **Cost math**: ES half-spread is 1 tick = 0.25pt on a ~$300k+ notional
  (~0.2bp); commission ~$1–2.5/side (<0.1bp). Round trip ~1bp of notional vs
  an expected hold-level move of hundreds of bp at multi-week horizons, at
  weekly-to-monthly turnover. This is the mirror image of the equity failure:
  cost floor 2–3 orders of magnitude below the gross move being harvested.
- **Data**: continuous daily series exist free (Yahoo `ES=F`-style, 2000→now,
  ~26y; probed 2026-08-29, table below) **but are front-month splices with
  unadjusted roll gaps** — for contango-heavy markets (CL, VX) the splice
  fabricates large negative/positive "returns" at every roll. A trend study
  on unadjusted splices is invalid by construction. Phase A must produce
  back-adjusted continuous series (see Data plan).
- **Platform fit (later, only if earned)**: axtrade is equities-shaped —
  futures need contract metadata (multiplier, tick size), roll handling, and
  a margin model in sizing/risk. None of that is needed for offline research.

### T2 — Volatility risk premium (VIX term structure / implied-vs-realized)

- **Evidence base**: real, persistent premium (VRP literature; short-vol
  carry when VIX futures are in contango), but with catastrophic left tail
  (Feb 2018 XIV wipeout) — position sizing IS the strategy.
- **Blockers**: needs VIX futures term-structure history (CBOE data; Yahoo's
  `^VIX3M` served 1 row in the probe) and instruments the platform has no
  concept of (options or VX futures). ETF proxies (SVOL, 2021→) have too
  little history to evaluate a tail-risk strategy honestly.
- **Verdict**: park as second thread. Revisit only with a proper VX
  term-structure dataset; do not evaluate on ETF-proxy history.

### T3 — Multi-day equity factor models (3–20 day holds)

- Blocked in practice: the honest version needs point-in-time,
  survivorship-clean universe data (the known F4 limitation; optional
  iteration A was never approved), and it walks straight back toward the
  closed dataset. Not this cycle.

**Pick: T1.** Best evidence base, cheapest data phase, cost structure that
actually fits the diagnostic lesson, and it reuses the phase-6 research-layer
pattern (plain pandas, no asyncio) unchanged.

## Data probe (2026-08-29, Yahoo daily, `period="max"`)

| Ticker | Instrument | Rows | Coverage |
|---|---|---:|---|
| ES=F | S&P 500 e-mini (cont. splice) | 6,551 | 2000-09 → 2026-08 |
| NQ=F | Nasdaq 100 e-mini | 6,551 | 2000-09 → 2026-08 |
| ZN=F | 10y T-note | 6,513 | 2000-09 → 2026-08 |
| GC=F | Gold | 6,523 | 2000-08 → 2026-08 |
| CL=F | WTI crude | 6,532 | 2000-08 → 2026-08 |
| EURUSD=X | EURUSD spot | 5,901 | 2003-12 → 2026-08 |
| JPY=X | USDJPY spot | 7,735 | 1996-10 → 2026-08 |
| ^VIX | VIX index | 9,233 | 1990-01 → 2026-08 |
| ^VIX3M | VIX 3M | 1 | broken via Yahoo |
| DBMF | managed-futures ETF | 1,838 | 2019-05 → 2026-08 |
| SVOL | short-vol ETF | 1,330 | 2021-05 → 2026-08 |

## Phase A — data foundation (the only work authorised by this doc)

Deliverable: `data/futures/` (untracked) with back-adjusted continuous daily
series for ~10–20 liquid markets across ≥4 sectors, plus a hygiene report in
the style of the phase-6 one.

1. **Source decision**: candidates — build back-adjusted series from
   individual-contract data (Databento CME historical is cheap;
   Norgate is the retail standard; Stooq has free continuous series whose
   adjustment method must be verified) vs. correcting Yahoo splices by
   detecting roll dates. Decide on evidence: pull one contango-heavy market
   (CL) from two sources and diff the roll treatment.
2. **Hygiene gates** (all must pass before any signal work):
   - roll-gap audit: no return attributable to a contract switch;
   - cross-source spot check on ≥3 markets;
   - a **replication gate** (the buy_hold analogue): reproduce the
     literature's headline TSMOM result (12-month sign, 1-month hold,
     vol-weighted, ~2000–2012 window) with the right sign and rough
     magnitude on our data. If the published anomaly does not replicate on
     our dataset in its own sample period, the dataset (or our construction)
     is wrong — stop and fix before proceeding.
3. **Cost model**: per-market half-spread + commission table (in bp of
   notional) written down BEFORE pre-registration, from contract specs, not
   fitted.
4. Then and only then: draft `docs/futures-tsmom-preregistration.md`
   (binding, phase-6 format) — lookbacks, sizing, rebalance frequency, IS/OOS
   split, primary cell, kill criteria — and freeze it before the first run.

## Practical notes

- Live trading remains out of scope (nothing has earned it), and the live
  IBKR account is a **cash account** — futures would require a margin
  account. Irrelevant for offline research; recorded so nobody "just tries
  it" later. Standing rule unchanged: no API on the live login.
- Yahoo FX spot (`EURUSD=X`) has no carry — spot-only FX trend ignores the
  interest differential, which is a large fraction of FX trend P&L. Use FX
  futures (6E, 6J, …) in the basket instead, or exclude FX in cycle 1.
- DBMF/SG Trend serve as external sanity benchmarks for the 2019+ window,
  not as data.
