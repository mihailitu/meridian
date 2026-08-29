# Strategy research survey — synthesis and plan (2026-08-29)

Status: SURVEY COMPLETE, plan proposed. Nothing here is pre-registered; no IS
run may happen off this document. Four deep-research threads (academic
short-horizon, practitioner forums, cost floors/venues, medium-horizon
published work) ran 2026-08-29; full reports with citations in
`docs/research-survey-2026-08/` (appendices A–D). This document extends
`docs/research-new-asset-classes.md` (the T1 scoping doc) and sits outside the
phase-7 stopping rule (new data / new instruments only).

## 1. The 1–2 minute question: CLOSED, four ways

The question "is 1–2 minute trading doable for retail (short of HFT)?" now has
four independent answers, all no:

1. **Our own falsification** (phase 3–6): ~1–2bp gross/trade on 1m equity
   signals vs a measured 3–5bp/side cost floor.
2. **Independent academic falsification** (Appendix A §10): Mesfin 2026,
   pre-registered, 14 signal families on 5m MNQ futures — gross 0.07–1.5
   pts/trade, below the 2-pt round-trip cost, across the board.
3. **The venue arithmetic** (Appendix C): the cheapest retail venue on earth
   (ES/NQ, ~0.35–0.75bp round trip) still eats 55–180% of the ~0.3–1bp of
   alpha that plausibly exists at a 1–2 minute horizon; every other venue is
   worse by 3–200×. Passive execution doesn't rescue it — retail resting
   orders are the stale quotes in the latency-arbitrage race (Aquilina/
   Budish/O'Neill, QJE 2022: ~0.5bp structural tax).
4. **The practitioner record** (Appendix B §2): no credible, verifiable
   account of sustained net-positive generic minute-bar trading exists on ET/
   QuantConnect/blogs; the community's own best 37-strategy cost-on sweep had
   one survivor, which dies with honest slippage by its author's admission.

**Binding consequence:** no research thread in this track may target holding
periods under 15 minutes. Minute-scale signals are admissible only as (a)
entry-timing overlays on longer-horizon positions, or (b) rescaled to ≥15min
holds on index futures — and even those are low-priority.

## 2. What the survey says survives (ranked)

Recurring structure in everything that survives scrutiny: **≤1 round trip/day
in a ≤1bp instrument, or returns earned by holding, not trading.** And the
only fully auditable retail live record found (Rob Carver, 12 years,
reconstructed independently by an EliteTrader journal audit) is slow
diversified futures trend/carry — i.e., our T1.

| Rank | Candidate | Type | Why | Cost fit | Status |
|---|---|---|---|---|---|
| 1 | **T1: TSMOM on liquid futures** (already scoped) | risk premium + behavioral | Best evidence base; only auditable retail live record; three survey refinements below | excellent (weekly/monthly turnover, ~0.5–1bp instruments) | Phase A authorised in T1 doc; **amendments in §3** |
| 2 | **E1: pre-FOMC drift, shifted window** | claimed alpha, contested | Re-validated through Dec 2024 (Sharpe 0.5–0.6, in market ~5% of days); rebutted for the pre-2015 window — a live controversy our harness can settle | excellent (8 trades/yr, EOD, one liquid instrument) | Propose as pre-registered micro-experiment |
| 3 | **E2: last-half-hour intraday momentum** (Gao/Baltussen) | claimed alpha, contested | Mechanically tied to gamma-hedging flow; strongest version significant after costs on 60+ futures to 2020; US version called data-mining by Rosa 2022 | good (1 RT/day, index future) | Propose as pre-registered micro-experiment |
| 4 | **E3: insider-purchase reaction** (EDGAR Form 4, 2d–2mo holds) | claimed alpha | Persists in recent samples; edge concentrated days after filing — our horizon band; free data | moderate (small-cap spreads — cost model critical) | Backlog; needs data-pipeline work |
| 5 | Crypto funding carry | risk premium | Costs structurally irrelevant (earn by holding); but Sharpe 6.45 (2020–23) → negative 2025; exchange/counterparty risk ≫ market risk | excellent | Monitor only; revisit if funding regime returns |
| 6 | Swing equity mean-reversion (2–5d, Alvarez-style) | claimed alpha, decaying | Survived $0.01/share costs historically; author reports shrinking edges | moderate | Backlog, behind E1–E3 |
| — | Defensive ETF rotation / put-write | beta timing / risk premium | Not alpha; live ≈ backtest −2–4%/yr (Allocate Smartly registry) | good | Personal-portfolio question, not strategy research |

**Dead / skip (evidence in appendices):** ORB as published (breaks even at
realistic slippage; one-regime PnL), overnight-effect trading (gross huge, net
−32% over 27y; NightShares ETFs liquidated; NY Fed: drift ~zero since 2021),
US turn-of-month, index inclusion, large-cap PEAD, mechanical iron condors
(≈flat since 2010), VIX term-structure rules (negative alpha OOS since
publication), unhedged short-vol (XIV −96% in one session), full cross-asset
carry (engine is breadth we can't hold), OFI/L2 microstructure (the alpha IS
the spread; wrong customer), CFDs (strictly dominated by futures).

**Meta-findings to internalise:**
- Publication kills capacity-thin anomalies within ~2 years (overnight drift,
  leveraged-ETF intraday momentum, crypto carry post-ETF). Any 2023–24
  retail-marketed paper is already being arbitraged.
- Data-mining flags concentrate in retail-marketed papers (zero-slippage
  fills, parameter searches, commercial incentives); the sober literature is
  uniformly negative. Trust the genre split.
- Quantopian's 888k-backtest study: backtest Sharpe had ~no OOS predictive
  value at population scale. Our pre-registration discipline is the only
  known defence; keep it binding.
- Free decay-detection layer to monitor: Quantseeker, Quantpedia OOS
  tracking, Allocate Smartly live registry.

## 3. Amendments to the T1 scoping doc (binding on its Phase B pre-registration)

From Appendix D §1, three survey findings must be reflected when
`docs/futures-tsmom-preregistration.md` is drafted:

1. **Benchmark = vol-targeted long-only portfolio**, not raw buy-and-hold.
   Kim/Tse/Wald 2016: vol-scaling contributes most of published TSMOM alpha;
   without this control we'd attribute risk-parity beta to the trend signal.
2. **Lookbacks ≥ ~3 weeks; blend medium+slow speeds.** Sub-weekly trend is
   microstructurally dead (arXiv 2607.01550); Man Group: fast speeds have
   lower net Sharpe. Use Baltas–Kosowski-style turnover reduction.
3. **Honest prior: net Sharpe 0.3–0.5, mostly risk premium.** Huang et al.
   2020 caps the alpha claim. Trend hedges slow bears, fails fast shocks —
   crisis-alpha claims stay out of the pre-registration.

## 4. Proposed plan

**Track order: T1 Phase A first (unchanged), micro-experiments E1/E2 as cheap
parallel work, E3 backlog.** Each experiment gets its own one-page binding
pre-registration (phase-6 format: frozen constants, primary cell, kill
criteria, one tuning pass, one OOS shot) BEFORE its first run.

- **T1 Phase A** (authorised by the T1 scoping doc, now amended per §3):
  back-adjusted continuous futures series, roll-gap audit, cross-source
  check, TSMOM literature-replication gate, cost table. Unchanged deliverable.
- **E1 (FOMC window):** needs only daily SPY/ES data + the FOMC calendar
  (both free). Pre-register the exact window (close before meeting → close of
  meeting day), the sample split, and the kill rule; one run. Est. one day of
  work end-to-end.
- **E2 (last-half-hour momentum):** needs 1m index data. Our archive is
  constituents, not the index — either construct a cap-weighted proxy from
  our S&P 1500 1m bars or download SPY/ES 1m history. Pre-register primary
  cell (first-half-hour + rest-of-day predictors, last-30min hold) per
  Gao/Baltussen; one run. The Rosa-vs-global-evidence dispute makes this a
  genuine open question, not mining.
- **E3 (insider filings):** requires an EDGAR Form 4 ingestion pipeline +
  small-cap cost model. Defer until E1/E2 verdicts land.
- **E4 (event-association study):** descriptive research, not a strategy —
  attribution of large moves to scheduled events, digestion-speed curves on
  the 1m archive, event-conditional baselines that E1 freezes its cell from,
  and a written decision gate that is the only path to resurrecting ML
  (audit B2). Plan: `docs/event-study-plan.md` (added 2026-08-29).
- **Not in scope:** anything sub-15min; options/VX infrastructure; L2 data;
  crypto execution. Live trading remains out of scope entirely.

**Stopping discipline for this track** (proposed, to be confirmed): each of
T1/E1/E2 gets one pre-registered cycle. Failures close the thread with a
written verdict, phase-6 style. This track has no "platform is the
deliverable" backstop left to prove — its only honest outputs are verdicts.

## 5. Verification items

- CME/IBKR fee numbers to re-verify against the CME fee finder before any
  cost table is frozen (ZN ~$0.87, 6E ~$1.60, MGC $0.60-vs-$1.10 conflict).
- Futures spread/slippage figures in Appendix C are modeled — one day of MES
  tick observation before committing to the futures cost model.
- Reddit/r/algotrading was inaccessible to the research environment; forum
  coverage has that gap (Appendix B method note).
