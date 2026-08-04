# Phase 7: Validation close-out + F1 low-turnover retest

> Drafted 2026-08-04, the evening of the IBKR validation day (S0+S1 PASS,
> D1–D6 merged — see `ibkr-connection-design.md` and
> `live-validation-2026-08-04.md`). Rationale discussed with the user the
> same evening: the platform is now ahead of everything else; the only
> evidence-backed research thread left is phase 6's F1 finding — a real
> overnight-reversal signal (IC t=+3.1, +20.6% gross) killed by turnover
> costs, not by absence of signal. Cost-death is a different death than
> no-signal-death, and it has a testable follow-up: lower-turnover
> expressions of the same signal.

## Shape: two tracks + a binding stopping rule

- **Track P — platform/validation close-out**: finish what the validation
  ladder started, fix the one unexplained wrong number, batch the small
  hygiene items. Bounded work; no new scope.
- **Track R — research: F1 low-turnover retest**: one more pre-registered
  cycle under the phase-6 discipline, on the same data foundation, using
  the still-virgin 2025-08→2026-02 half for at most one OOS shot.
- **Stopping rule (binding, per the 2026-08-04 agreement)**: if this cycle
  dies — IS kill or OOS kill — strategy research **on this dataset closes
  permanently**. No third cycle, no "one more idea". The project's
  deliverable then becomes the platform itself (Track P wrap-up plus a
  documentation/write-up pass). This rule exists for the same reason
  pre-registration does: the discipline that made the phase-3/phase-6
  kills trustworthy is the discipline that prevents hypothesis-mining.

## Track P iterations

| # | Iteration | Source | Status |
|---|-----------|--------|--------|
| P-1 | **Indicator warmup anomaly root-cause + fix** (S1 finding 3). Working hypothesis: aggregator seeds IndicatorEngine buffers from TimescaleDB history at startup, and that history held July's mock-run bars at mock price levels — predicting the observed impossible SMA20=275 against real 304 closes. Plan: read the warmup path; write a deterministic repro test (restart with stale-history DB → assert either clean-warmup NULLs or correctly-seeded values); fix; if the hypothesis is wrong, root-cause whatever is. Gate: repro test red→green; next validation run shows sane warmup from bar 1. | S1 finding 3 | PLANNED |
| P-2 | **Validation + API hygiene batch** (implementer-grade): (a) state-reset step for validation runs — extend `reset-paper-trading.sh` or a sibling script to flush the axtrade Redis streams and truncate live-DB bar tables, and reference it in the validation docs; (b) `/api/gateway/status` reports runtime truth, not config (July part-1 finding 1); (c) discovery `discovered_at` 3h-off naive-datetime bug (July part-1 finding 2); (d) decide vestigial `bars.regime` column: drop or populate (July part-1 finding 3). Gate: unit tests + one mock `start-all.sh` smoke confirming the status endpoint and timestamps. | S1 finding 2; live-validation-2026-07-19 findings 1–3 | PLANNED |
| P-3 | **S3 — IBKR order path** (attended, market hours, ~30 min): scripted per the design doc — 1-share MARKET buy → fill in `fills`/`positions` AND the TWS blotter; far LIMIT buy → cancel → terminal status, no fill; `get_positions()` reconciles. Gate: DB and TWS agree exactly. Optionally fold the still-pending Alpaca part-2 session into the same market day (separate adapter, same checks). | design doc S3; live-validation-2026-07-19 "Part 2 pending" | PLANNED |
| P-4 | **S2 soak / S4 strategy loop / S5 unattended — PARKED.** Scheduled only when something earns unattended runtime. If Track R dies, the S5 ladder can still be justified once as an infrastructure proof (benchmark buy_hold live-paper for a day) as part of the platform write-up — decide then, not now. | design doc S2/S4/S5 | PARKED |

Sequencing: P-1 first (it is the only open correctness question in the
post-phase-3 era and touches every future run). P-2 parallel, delegatable.
P-3 next free market day. Track R may start after P-1 lands; it does not
depend on P-2/P-3.

## Track R iterations (pre-registered F1 retest)

Discipline carried over from phase 6 verbatim: exploratory work touches
only the IS half (2024-08→2025-08); the OOS half (2025-08→2026-02) stays
virgin until the single pre-registered shot; corporate-action guard
mandatory (the spinoff gap finding); costs at the pre-registered floor;
primary cell named in advance; verdicts by rule, not judgment.

| # | Iteration | Deliverable / Gate | Status |
|---|-----------|--------------------|--------|
| R-A | **Design space + cost model.** Enumerate low-turnover expressions of the F1 overnight-reversal signal: longer holding periods (2–5 day decay capture vs 1-day), entry thresholds that cut trade count (trade only extreme deciles / gap-size gates), turnover-aware portfolio construction (trade only decile *changes*), and instrument variants (the S&P 1500 single-name universe vs liquid-ETF proxies with tighter effective spreads). For each: expected turnover, cost at the floor, required gross to survive. Kill on paper anything that cannot clear costs even at phase-6 F1's measured gross. Gate: shortlist (≤3 cells) + cost table, IS-half exploratory evidence only. | draft pre-registration | PLANNED |
| R-B | **Binding pre-registration** committed before any Phase-C run: families, exact rules, primary cell, cost floor, corporate-action guard, IS pass/kill thresholds, the one-OOS-shot condition, and the phase-7 stopping rule restated. Same standard as `phase6-preregistration.md`. Gate: committed doc, then frozen. | `docs/phase7-preregistration.md` | PLANNED |
| R-C | **One frozen IS run** of the pre-registered grid → verdict by rule. Only on an IS pass: the single OOS shot on the virgin half. Gate: verdict recorded in the phase doc + ROADMAP either way; if killed, the stopping rule executes (research on this dataset closed permanently). | IS verdict; possibly the OOS shot | PLANNED |

## Progress log

- 2026-08-04: Phase drafted and committed. All iterations PLANNED.
