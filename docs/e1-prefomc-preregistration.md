# E1 — Pre-FOMC drift, shifted window: Pre-registration (BINDING)

> Drafted 2026-08-29, before any E1 stability cell was computed. Once any
> number from §5 exists, nothing here may change for this cycle. A spec bug
> found later is fixed via a dated amendment at the bottom **before rerunning**;
> results computed under the buggy spec are discarded, not compared. Format and
> discipline follow `phase6-preregistration.md`.

## 1. Claim under test and its status

The survey (thread D) flagged a contested claim: the classic Lucca–Moench
24-hour pre-FOMC drift died after 2015 (Kurov, Gilbert & Wolfe), but a
*shifted* window — close of the day before a scheduled FOMC decision to the
decision-day close — reportedly remained profitable through Dec 2024
(~4% CAGR on SPY, Sharpe 0.5–0.6, in market ~5% of days).

## 2. Contamination disclosure (why this is NOT an out-of-sample test)

E4 Phase 1 (`docs/event-study-plan.md`, findings table, 2026-08-29) already
computed the full-sample statistic on this exact window and instrument class:
+21.5 bp mean / +4.3 bp median per meeting, t=2.57 vs zero, t=2.31 vs
baseline, n=212 scheduled meetings 2000→2026, ^GSPC. **That look is spent.**
Consequences, binding:

- The full-sample mean, median, and t-stats are *priors*, not evidence this
  cycle may re-count. No E1 conclusion may cite them as its result.
- Anything derived trivially from them is also considered seen — e.g. "share
  of positive meetings > 50%" follows from the positive median and may not be
  a gate condition.
- What has genuinely **never been computed** on our data: sub-sample splits,
  post-2016 sub-sample, trimmed/tail-excluded estimators, per-meeting return
  series on SPY (Phase 1 used ^GSPC), cost-netted figures. The gate (§6)
  binds only on these unseen cells.
- A true out-of-sample test exists only in the future: the forward tally (§7).

## 3. Data and instrument (frozen)

- Meetings: scheduled FOMC decision days only, from the certified loader
  (`axtrade.research.events`, `event_dates(cal, "fomc", scheduled_only=True)`),
  calendar as committed in 6128d59. Coverage 2000-02→2026-07; no meeting
  added or removed mid-cycle. Unscheduled/emergency actions are excluded
  (they are not forecastable calendar entries).
- Instrument: **SPY daily, dividend-adjusted closes** (Yahoo `auto_adjust=True`),
  cached once to `data/research/event_study/spy_daily_adj.parquet` at first
  run and not re-downloaded mid-cycle. Adjusted closes so an ex-div date
  inside the two-day window does not read as a fake loss. ^GSPC is not
  re-used: E1's number must be on the tradeable instrument.
- Per-meeting return r_i: log(adjClose(t)) − log(adjClose(t−1)), where t is
  the decision day and t−1 the prior trading day. Meetings where either close
  is missing are dropped and counted.
- Baseline where needed: all non-FOMC trading days' 1-day log returns over
  the same coverage window.

## 4. Trade specification and cost model (frozen)

- The implied trade: long SPY, buy MOC at t−1, sell MOC at t. One round trip
  per scheduled meeting (8/yr), no leverage, no overlap.
- Cost: **2 bp per round trip** charged to every per-meeting return
  (SPY spread ≈ 0.2 bp/side at current prices, plus slippage/commission
  buffer). Net return: nr_i = r_i − 2 bp. This is deliberately generous to
  the null (real SPY MOC cost is lower).

## 5. Stability cells (computed exactly once, all frozen before computation)

- **S1 — halves.** Split the 212 meetings at the count midpoint (meetings
  1–106 / 107–212, i.e. roughly 2000→2013 / 2013→2026). Report mean, median,
  t vs zero of nr_i in each half.
- **S2 — post-rebuttal era.** Meetings with t ≥ 2016-01-01 (the sub-sample
  where the *classic* window is claimed dead; n ≈ 84). Report mean, median,
  t vs zero of nr_i.
- **S3 — tail dependence.** On the full sample: (a) 10%-trimmed mean of nr_i
  (drop the 10% largest and 10% smallest); (b) mean of nr_i excluding the 5
  largest |r_i| meetings. Report both.
- **S4 — regime description (non-binding).** nr_i by meeting outcome (hike /
  cut / hold, from the realized target-rate change) — descriptive context
  only, reported but feeding no decision (outcome is not knowable at entry).

No other cells. No window variants, no other instruments, no other cost
points feeding decisions.

## 6. Advance/kill rule (BINDING, conjunctive)

E1 **advances** to the forward paper sleeve (§7) iff ALL of:

1. S1: mean nr > 0 in **both** halves.
2. S2: mean nr > 0 **and** t vs zero ≥ 1.0 (threshold modest by design:
   n ≈ 84 one-day returns has limited power; the sign requirement is doing
   the work).
3. S3: both tail-robust estimators > 0 (10%-trimmed mean, and mean excluding
   top-5 |r| meetings).

Anything else ⇒ **kill**: E1 closes with a written verdict in this file
("shifted-window drift is a tail/regime artifact on our data"), and the
pre-FOMC thread ends — no re-tests on variant windows or instruments without
a new pre-registration on data this cycle did not use.

Multiple-comparison stance: one hypothesis, three conjunctive sub-tests
(conjunction only lowers false-advance probability); S4 is explicitly
non-binding.

## 7. Forward paper tally (the only true OOS)

If §6 advances: from the first scheduled meeting after this document's
commit date, record for every scheduled meeting the realized nr_i under §3–§4
definitions, appended to `data/research/event_study/e1_forward_tally.csv`
(no trading, paper record only; live/paper OMS integration is a separate
decision E1 does not make). Evaluation checkpoint: after **24 meetings**
(~3 years), E1's forward verdict is positive iff cumulative net log return
> 0. Before 24 meetings, no verdict is drawn from the tally and no early
stop is triggered by drawdown (8 observations/yr cannot support one).

## 8. What implementation may and may not do

- MAY: implement §3–§5 as a tier-2 script in `scripts/research/event_study/`
  (e1_stability.py), with the certified events loader; sanity-assert n=212
  scheduled meetings and coverage endpoints before computing.
- MAY: fix bugs found before the first successful run completes; a bug found
  after seeing numbers follows the amendment protocol in the header.
- MAY NOT: compute any cell not in §5, any alternate window/instrument/cost,
  or re-derive the full-sample table (it exists in the E4 doc; re-computing
  it on SPY for "comparison" is allowed **only** as the by-product full-sample
  mean/median/t of nr_i, reported next to the prior, never gating).
