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
