# Phase 6 / Phase B: Pre-registration (BINDING)

> Committed 2026-07-19, before any Phase C computation. This document freezes
> the hypothesis families, data conventions, portfolio construction, cost
> model, corporate-action guard, and kill/advance rules for the
> cross-sectional daily track (`phase6-cross-sectional.md`). Once a Phase C
> number has been computed, nothing in this file may change for the current
> IS/OOS cycle. If Phase C reveals a spec bug (wrong formula, look-ahead), the
> fix is committed as an amendment section at the bottom of this file **before
> rerunning**, with the bug described; results computed under the buggy spec
> are discarded, not compared.

## 1. Data and windows

- Inputs: `data/daily/daily_bars.parquet`, `data/daily/eligibility.parquet`,
  `data/daily/calendar.txt` exactly as produced by Phase A (commit `3f66c2e`).
  No rebuilds mid-cycle.
- **IS window**: formation dates D with 2024-08-01 ≤ D and the full holding
  period realized on or before 2025-08-01. All Phase C research runs on IS
  only.
- **OOS window**: formation dates 2025-08-01 ≤ D with holding realized on or
  before 2026-01-30. Formation *lookbacks* may reach back across the
  boundary into IS data (that is history, not selection leakage). OOS is run
  once, by Phase D, for families that pass the IS gate — zero peeks before.
- Trading days and alignment come from `calendar.txt` (376 days). "D+1"
  always means the next calendar entry, not the symbol's next row.

## 2. Universe at formation

A symbol enters the ranking pool on formation date D iff **all** of:

1. `eligible == True` in `eligibility.parquet` as of D (trailing 63-day
   coverage ≥ 90%, trailing median RTH dollar volume ≥ $5M, ≥ 21 days since
   first appearance — computed with no look-ahead; see
   `research/universe.py`).
2. `rth_close(D) ≥ $5.00` (penny-stock guard).
3. Corporate-action guard (§5) does not exclude it.
4. The formation signal is computable: every daily field the family's signal
   formula needs is present over its lookback (no imputation of missing
   formation days; a gap in the lookback disqualifies the name for that D
   only for families whose formula spans the gap — operationally: F1 needs
   row D with `prev_rth_close` present; F2/F3 need the two endpoint closes
   of their compounding window present).

SPY is never in the pool (benchmark only).

## 3. Families, grids, and primary cells

Signals are oriented so **higher signal = higher predicted forward return**;
the long side is always the top decile of the oriented signal.

### F1 — Cross-sectional overnight reversal (1 cell)
- Signal at D: `−intraday_ret(D)` = −(rth_close/rth_open − 1).
- Entry: long top decile at `bar1600_close(D)` (closing-auction proxy;
  implementable as an MOC order decided on the 15:59 signal). Fallback when
  `bar1600_close` is missing (~0.4% of symbol-days): `rth_close(D)`; count
  and report fallbacks.
- Exit: `rth_open(D+1)` (MOO order).
- Grid: none. **Primary cell = the only cell.**
- Turnover: 2 sides per day per unit capital (full round trip daily).

### F2 — Short-term reversal (9 cells)
- Signal at D: `−[rth_close(D)/rth_close(D−J) − 1]`, J trading days.
- Entry: `rth_open(D+1)`. Exit: `rth_open(D+1+H)`.
- Grid: J ∈ {1, 3, 5} × H ∈ {1, 3, 5}. **Primary cell: J=5, H=5** (the
  classic weekly-reversal spec; chosen a priori, not for data reasons).
- Holding via overlapping tranches: a new tranche forms each trading day
  with 1/H of capital; portfolio return on a day is the equal-weighted mean
  of active tranches' returns.

### F3 — Cross-sectional momentum (2 cells)
- Signal at D: `rth_close(D−skip)/rth_close(D−skip−J) − 1`, skip = 5 trading
  days (skip-week), positive orientation (winners long).
- Entry: `rth_open(D+1)`. Exit: `rth_open(D+1+21)`. Overlapping tranches as
  in F2 (H = 21).
- Grid: J ∈ {63, 126}. **Primary cell: J=63** — chosen for usable-window
  length (J=126 leaves ~6 months of IS formation dates; J=63 leaves ~9),
  fixed here before seeing any result.
- Survivorship caveat from Phase A applies most strongly here; cited with
  results, not a gate input.

**Multiple-comparison accounting**: exactly 3 binding tests (one primary
cell per family). Non-primary grid cells are descriptive robustness
context only — **a family whose primary cell fails is killed even if another
cell looks good**; resurrecting a non-primary cell requires a new
pre-registered cycle on data not used here.

## 4. Portfolio construction and accounting

- Rank the pool by oriented signal each formation date; split into 10
  equal-count deciles (`qcut` on average-tied ranks). All 10 decile
  portfolios are computed (monotonicity diagnostics); the long-short
  top-minus-bottom spread is measured for characterization but **never**
  feeds the advance rule (no OMS short support).
- Equal weight within a decile at formation; no intra-hold rebalancing;
  weights drift with returns within a tranche.
- Per-name hold return uses the entry/exit prices of §3. If the exit-day row
  is missing for a name, exit at the next available `rth_open` within 5
  trading days; if none (delisting/halt), exit at the name's last observed
  `rth_close`. Count and report every such event. (Optimistic for M&A
  cash-outs; acceptable and flagged.)
- **Costs**: sweep {0, 2, 5, 10} bp per side, charged on every dollar
  traded (entry and exit each pay one side; F2/F3 tranche turnover is 2
  sides per H days per unit of tranche capital). **The binding cost point is
  5 bp/side.**
- No compound-vs-simple ambiguity: portfolio equity compounds daily; period
  returns are geometric.

## 5. Corporate-action guard (BINDING, from the Phase A finding)

Split adjustment does not cover spinoffs/special dividends (DD 2025-11-03:
−58.7% fake overnight crash; CORT 2025-12-31 suspect). Guard, applied to
**all families** at formation date D:

> Exclude a symbol from the ranking pool at D if `|gap_ret| > 0.25` on any
> day in [D − J_formation, D], where J_formation is the family's signal
> lookback in trading days (0 for F1, J for F2, J + skip for F3).

Rationale: every one of the 13 |cc_ret| > 50% days in the data is
gap-dominated; a 25% overnight gap threshold catches the fake crashes
(−58.7%, −50.4%) with margin while excluding only a handful of real
extreme-news names, whose formation prices are least trustworthy anyway.
Symmetric (|·|) for simplicity and reverse-split safety. The exclusion
count per formation date is reported. No manual per-symbol exclusion list
is used.

Known cost: this trims the deepest-loser tail that reversal families would
otherwise buy — accepted; a strategy that only works by buying >25%
overnight crashes is not implementable from this data anyway.

## 6. Benchmark

Equal-weight eligible universe, **matched to each family's leg
convention** (same entry/exit price fields and dates, all pool names
instead of one decile, zero cost). This isolates selection (ranking) from
beta/timing. The Phase A survivorship note (EW −13.4% vs SPY over the full
window; dividends excluded on both legs) is cited alongside every result.

## 7. Metrics computed per family (IS)

- Daily rank IC: Spearman(oriented signal at D, forward hold-period gross
  return), averaged over formation dates; t-stat with Newey–West lags =
  H − 1 (plain t for F1).
- Decile mean hold-period returns (monotonicity), long-side gross and net
  across the cost sweep, annualized net return and Sharpe at 5 bp,
  turnover, max drawdown, matched-EW-benchmark excess, and the quarterly
  table of §8.
- IS quarters: the four consecutive 3-month spans 2024-08→11, 2024-11→
  2025-02, 2025-02→05, 2025-05→08. A quarter is *available* to a family if
  it has formation signals on ≥ 2/3 of the quarter's trading days (warmup
  can void early quarters, especially F3 J=126).

## 8. Advance/kill rule (BINDING, evaluated on the primary cell only)

A family **advances to the OOS shot** iff all four hold on IS:

1. **Net viability**: long-side net total return > 0 at 5 bp/side.
2. **Selection**: long-side *gross* total return exceeds the matched EW
   benchmark's over the same legs.
3. **Consistency**: long-side net return at 5 bp positive in at least
   (n − 1) of its n available quarters, with n ≥ 2 required (n < 2 ⇒ kill:
   not enough history to judge consistency).
4. **Signal sanity**: mean rank IC > 0 with |t| ≥ 2.0 (Newey–West per §7).

Anything else ⇒ **kill**, written up in the phase doc. No re-tuning, no
cell-switching, no threshold-nudging after results exist. If all three
families die, the track closes per `phase6-cross-sectional.md` Phase D.

## 9. What Phase C may and may not do

- MAY: implement the above in `src/axtrade/research/` with unit tests
  (correctness tests on synthetic frames are encouraged and are not
  "peeking"), run the frozen grid on IS, produce one report.
- MAY: fix implementation bugs found via unit tests before the first IS run.
- MAY NOT: add families, cells, filters, or metrics that feed decisions;
  change thresholds; run anything on OOS dates; re-run "variants" of the
  primary cells. Exploratory numbers, once seen, cannot be un-seen — if an
  unplanned analysis happens by accident, it is disclosed in the report and
  cannot upgrade a kill to an advance.
