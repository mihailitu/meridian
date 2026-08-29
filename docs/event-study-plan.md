# E4 — Event-association study (plan, 2026-08-29)

Status: DRAFT plan. Descriptive research, NOT a strategy and not a
pre-registration. Its outputs are facts about our data, a feed into E1's
pre-registration, and — only if its pre-specified gate is met — the "new
written case" the ROADMAP requires before any ML resurrection (retired audit
B2; phase-4 deletion stands until that case exists).

## 1. Purpose and stance

Measure how much of market movement is *event-scheduled* vs unexplained, and
how fast prices digest each event type — on our own data. This is
explanation, not prediction: it claims nothing about the future and therefore
cannot be overfit into a fake strategy. It exists because:

- the user's standing interest is understanding moves ↔ events (the original
  ML motivation), done honestly this time;
- E1 (pre-FOMC window) needs event-conditional baselines anyway;
- any future ML experiment needs to know whether there is *any* structure
  worth modeling at horizons/costs we can trade (survey: nothing sub-15min;
  daily+ only).

Hard guardrails, binding for this study:
- **No fitted trading rules.** Only pre-specified descriptive statistics.
  Every definition (window, threshold, universe) is written in §4 BEFORE
  looking at results; changes require an amendment note here.
- **No pretrained-LLM sentiment on historical text.** A pretrained model
  knows what happened after the text was written; its "predictions" on our
  sample would be contaminated by construction. Event *timing* and *counts*
  only in this phase.
- **Timestamp hygiene:** only event sources with officially published
  schedules/timestamps (§3). No scraped news archives with editable
  timestamps in the quantitative core (GDELT is quarantined to Phase 3,
  exploratory, clearly labeled).

## 2. Questions (pre-specified)

- **Q1 — Attribution of large moves.** Of days where the index (and, cross-
  sectionally, our S&P 1500 names) moved more than 2 trailing-σ, what
  fraction fall on: FOMC decision days, CPI days, NFP days, other scheduled
  macro days, the name's own earnings day (cross-section only), none of the
  above? Long history (Yahoo daily, 2000→) for the index; our daily research
  layer (2024-08→2026-02) for the cross-section.
- **Q2 — Digestion speed.** Using the 1m archive: realized-volatility and
  cumulative-return curves minute-by-minute around scheduled event times
  (14:00 ET FOMC statement, 14:30 press conference; 08:30 ET CPI/NFP — note
  pre-market, so first RTH minutes carry it). How many minutes until vol
  reverts to the day-type baseline? This directly tests, on our data, the
  literature claim that scheduled information is priced in minutes.
- **Q3 — Event-conditional drift.** Mean/median/dispersion of index returns
  in windows around FOMC (t−1 close → t close, matching E1's disputed
  window; also t+1..t+3), CPI, NFP — versus unconditional same-weekday
  baselines, with t-stats. This IS E1's baseline table; E1's
  pre-registration will freeze its cell from this.
- **Q4 — Earnings share of idiosyncratic risk.** For our S&P 1500 daily
  panel: what fraction of each name's largest 5 moves in the window are its
  earnings days? Distribution of earnings-day |move| vs non-earnings.
  (Bounds how much single-name "news prediction" could even matter.)
- **Q5 (Phase 3, exploratory only) — Unscheduled news.** GDELT 15-min news
  volume spikes vs index moves: does news volume LEAD or LAG the move?
  Hypothesis from the literature: it lags (news reports the move). Labeled
  exploratory; nothing downstream may cite it as evidence.

## 3. Data sources

| Source | For | Timestamp quality | Cost |
|---|---|---|---|
| Fed website FOMC calendars (2000→) | Q1–Q3 | official, exact | free |
| BLS release schedules (CPI/NFP/PPI, 2008→ archived) | Q1–Q3 | official, 08:30 ET | free |
| Yahoo daily: ^GSPC/^NDX/ES=F (2000→) | Q1, Q3 long history | daily — sufficient | free |
| Our 1m parquet archive (S&P 1500, 2024-08→2026-02) | Q2, Q4 | exchange timestamps, hygiene-certified | have |
| Our daily research layer (`data/daily/`) | Q1 cross-section, Q4 | derived from above | have |
| Earnings dates+session (BMO/AMC) per symbol | Q4 | **⚠ open item** — candidates: Alpaca calendar API, yfinance `earnings_dates`, Nasdaq API; accuracy must be spot-checked against 20 known reports before use | free tiers |
| GDELT 2.0 event/GKG feed | Q5 only | machine 15-min buckets; content noisy | free |

The earnings-calendar verification is the only real data risk: wrong BMO/AMC
session tags flip which trading day "owns" the reaction. Gate: 20-name manual
spot-check ≥95% correct, else Q4 is restricted to date-only (±1 day window).

## 4. Frozen definitions

- "Large move": |daily log return| > 2 × trailing 63-day σ (index), > 2 ×
  trailing 63-day idiosyncratic σ vs SPY beta (names).
- Q2 event window: [−30, +120] minutes around the official timestamp;
  baseline = same-minutes curve on matched non-event days (same weekday, no
  scheduled macro release).
- Q3 windows: FOMC {t−1c→tc, tc→t+1c, t+1c→t+3c}; CPI/NFP {t−1c→to, to→tc}.
  t-stat threshold for "notable": |t| ≥ 2 (reported regardless).
- Universe for cross-sectional questions: the phase-6 eligible universe
  (`research/` eligibility, ~1,350 names/day) — no new universe definitions.

### 4a. Phase 2 amendments (pre-specified 2026-08-29, before any Phase 2 result was examined)

- **Q2 instrument:** SPY 1m from the archive (index proxy; ES futures parquet
  in the archive named "ES" is the equity ticker ES, Eversource Energy, not the
  future — not used). Timestamps are naive-UTC bar starts; convert to ET exactly as
  `research/daily.py` does.
- **Q2 curves:** build a complete 1-minute grid over [−30, +120] minutes
  around the official event minute (FOMC 14:00 ET, presser 14:30 marked on
  plots; CPI/NFP 08:30 ET using extended-hours bars — note thin pre-market
  liquidity in the writeup). Prices forward-filled onto the grid within each
  day; per-offset volatility = cross-event mean of |1m log return|;
  drift curve = cross-event mean cumulative log return from the event minute.
- **Q2 baseline:** identical construction on matched days — same weekday, no
  scheduled fomc/cpi/nfp event, within the archive window.
- **Q2 "minutes to baseline" (frozen):** smooth both vol curves with a
  trailing 5-minute mean; the digestion time is the first offset m ≥ 0 at
  which smoothed event vol ≤ 1.25 × smoothed baseline vol and stays there for
  10 consecutive minutes. The full ratio curve is reported alongside so the
  single number can be sanity-checked by eye.
- **Q4 earnings→reaction-day mapping (frozen):** BMO → that trading day;
  AMC → next trading day; unknown/unverified session → date-only, a move on
  either the date or the next trading day counts (the §3 fallback).
- **Q4 statistics (frozen):** universe = phase-6 eligible names with ≥ 250
  rows in the daily panel. (i) Per name: share of its top-5 |cc_ret| days
  that are earnings-reaction days; report the cross-name distribution.
  (ii) Panel: median and p90 of |cc_ret| on earnings-reaction days vs all
  other days. (iii) Share of >2σ idiosyncratic moves (rolling 63d OLS beta
  vs SPY cc_ret, residual σ, shifted — §4) falling on earnings-reaction days
  — the cross-sectional counterpart of Q1.
- **Earnings source:** Nasdaq earnings-calendar API by date (primary, gives
  BMO/AMC tags), yfinance `earnings_dates` as an independent cross-check on a
  random sample; the §3 gate (20-name manual spot-check, ≥95% correct)
  decides whether session tags may be used or Q4 drops to date-only.

## 5. Phases and deliverables

- **Phase 1 — calendars + daily (est. ~1 day):** build the event-calendar
  dataset (FOMC/CPI/NFP, 2000→, one parquet + loader in
  `src/axtrade/research/events.py`), run Q1 + Q3. Deliverable:
  `data/research/event_study/` outputs + findings section appended to this
  doc. Q3's FOMC table hands E1 its baseline.
- **Phase 2 — intraday digestion (est. ~1 day):** Q2 + Q4 on the 1m archive
  via the existing research layer (plain pandas, no asyncio). Deliverable:
  digestion-speed curves (minutes-to-baseline per event type) + earnings
  share table, appended here.
- **Phase 3 — exploratory GDELT (optional, decide after Phase 2):** Q5.
  Time-boxed to one day; whatever it shows, it stays labeled exploratory.

## 6. Decision gate for any ML experiment (the "new written case" test)

An ML experiment (one, pre-registered, phase-6 rules) may be proposed ONLY if
Phase 1–2 findings show ALL of:

1. a post-event drift or conditional pattern with |t| ≥ 2 at a horizon
   ≥ 1 day (inside the cost-viable zone from the survey);
2. turnover implied by trading it ≤ ~1 round trip/day in an instrument with
   round-trip cost ≤ ~1bp (index futures) or ≤ 2 trades/week in equities;
3. a plausible mechanism (who is on the other side and why they persist).

If met, the case is written as an amendment here, and the experiment gets its
own binding pre-registration (simple regularized model vs dumb baseline,
out-of-sample after costs, kill rule frozen before the run). If not met, the
ML question closes with a written verdict, and B2 stays retired.

Not authorised by this document under any outcome: platform ML
infrastructure, sub-daily prediction targets, LLM sentiment pipelines,
unscheduled-news trading.

---

## Phase 1 findings (2026-08-29)

Code: `scripts/research/event_study/` (tier 2) + `src/axtrade/research/events.py`
(tier 1, 4 unit tests). Outputs: `data/research/event_study/` (untracked).

**Calendar built:** FOMC 220 decision/action days 2000-02→2026-07 (8
unscheduled actions flagged; 2020 correctly has 7 scheduled meetings — the
cancelled March 2020 meeting), CPI 214 and NFP 214 release days
2008-02→2025-12, all from officially date-stamped publications (Fed minutes/
statement URLs; BLS release filenames via Wayback snapshots of BLS's own
archive pages — bls.gov blocks direct fetches). Five statement-URL false
positives (Jackson Hole speeches, facility announcements, a first-day stamp)
were caught by the 8-meetings-per-year review check and curated out in the
fetch script.

**Q1 — attribution of large moves** (|z| > 2, trailing 63d σ; window
2008-02→2025-12, 4,486 days, 283 large moves):

| category | share of days | share of large moves | lift |
|---|---|---|---|
| FOMC | 3.2% | 4.6% | 1.42 |
| CPI | 4.7% | 5.0% | 1.05 |
| NFP | 4.6% | 4.2% | 0.91 |
| any macro event | 12.3% | 13.1% | 1.07 |
| no event | 87.7% | 86.9% | 0.99 |

**Finding: scheduled macro events explain almost none of the index's large
moves.** 87% of >2σ days fall on no-event days; only FOMC days are even
modestly enriched (a large move is ~1.4× likelier, ~9% of FOMC days). The
"predict the future from event calendars" premise fails at the index level —
whatever drives most big days is not on the schedule. (Single-name earnings
attribution: Phase 2.)

**Q3 — event-conditional drift** (scheduled events, log returns, bp):

| event | window | n | mean | median | base mean | t vs 0 | t vs base |
|---|---|---:|---:|---:|---:|---:|---:|
| FOMC | t−1c→tc | 212 | **+21.5** | +4.3 | +1.8 | **2.57** | **2.31** |
| FOMC | tc→t+1c | 212 | −11.0 | +1.1 | +2.9 | −1.15 | −1.45 |
| FOMC | t+1c→t+3c | 212 | +8.9 | +9.4 | +4.9 | 0.76 | 0.34 |
| CPI | t−1c→to | 212 | +3.0 | +0.7 | +1.6 | 0.90 | 0.41 |
| CPI | to→tc | 212 | +6.3 | +8.0 | +1.7 | 0.80 | 0.57 |
| NFP | t−1c→to | 209 | +3.4 | +3.9 | +1.6 | 1.12 | 0.59 |
| NFP | to→tc | 209 | +4.1 | +14.2 | +1.8 | 0.56 | 0.31 |

**Findings:** (a) **The shifted pre-FOMC window (E1's exact window) is
present in our data**: +21.5bp/meeting into the decision close, t=2.31 vs
baseline over 212 meetings 2000→2026 — ~170bp/yr gross while in the market
~3% of days. Median 4.3bp vs mean 21.5bp: right-skewed, the mean leans on
tail meetings — E1 must report robust statistics, not just the mean. (b) A
negative, non-significant post-decision day (−11bp, t=−1.15). (c) **CPI and
NFP: nothing** — no window reaches |t|=1.2. Event-calendar structure at the
index level is FOMC-specific.

**Binding note for E1:** this full-sample look means E1 can no longer claim
virgin out-of-sample on this window/instrument. Its pre-registration must be
designed around that: pre-specify subsample-stability tests (halves, regime
splits) and robust estimators, and treat this table as the *prior*, not as
evidence E1 re-counts.

**Limitations:** CPI/NFP coverage starts 2008-02 and ends 2025-12 (2026
release dates not yet cleanly sourced — verification item); index-level only;
earnings and digestion-speed questions are Phase 2.

---

## Phase 2 findings (2026-08-29)

### Q2 — digestion speed (SPY 1m, 2024-08→2026-01; §4a definitions)

Code: `scripts/research/event_study/q2_digestion.py`. Outputs:
`data/research/event_study/q2_{curves,summary}.csv`, `q2_{event}.png`.
Events inside the archive window: FOMC 12, CPI 16, NFP 16 (baselines: 123/
260/203 matched no-event days). Small n — the volatility curves are the
reliable object here; the drift curves are noise-dominated and none of the
drift numbers below should be read as evidence of direction.

| event | anchor | peak vol ratio (offset) | minutes to baseline (≤1.25×, sustained 10m) |
|---|---|---|---|
| FOMC | 14:00 ET | 3.5× (+39) | **never** within +120 (i.e. through the close) |
| CPI | 08:30 ET | 5.0× (+4) | **47** |
| NFP | 08:30 ET | 3.9× (+3) | never within +120 (hovers just above threshold post-open) |

**Findings.** (a) **The initial reprice is essentially instantaneous**: mean
|1m return| in the event minute is ~19bp (FOMC), ~37bp (CPI), ~24bp (NFP)
against ~2bp baselines — a 10–20× one-minute spike that collapses to 2–3×
within ~5 minutes. On the "can you react to the release?" question the
literature is confirmed on our data: the level move is done before a daily
system could act. (b) **But full digestion is slower than "minutes" for
FOMC**: the 14:30 press conference is a clearly visible second vol event
(re-spike to ~11bp at +33), and event-afternoon vol never returns to within
1.25× of baseline before the close. FOMC afternoons are elevated-vol
regimes end-to-end, not a spike plus calm. (c) CPI is the cleanest case of
fast digestion: back to baseline in ~47 minutes, i.e. about 15 minutes
after the 09:30 open (the +60 bump in both curves is the open itself,
present on baseline days too). (d) Drift context only: in this 12-meeting
sample, FOMC decision afternoons drifted ~−20bp cumulative into the close —
same sign as Phase 1's (non-significant) negative post-decision day; n=12,
not evidence. (e) Artifact note: the single leftmost offset (−30) of the
08:30 events is inflated in both curves by ffill-seeding across sparse
pre-market gaps; it affects nothing at offsets ≥ 0.

**Relevance to the §6 ML gate:** the only predictable vol structure sits in
the first 1–5 minutes after release — squarely inside the cost-infeasible
sub-15-minute zone the survey ruled out. Nothing in Q2 reopens sub-daily
prediction; the FOMC-afternoon elevated-vol regime is a risk-management
fact (position sizing on event days), not a signal.
