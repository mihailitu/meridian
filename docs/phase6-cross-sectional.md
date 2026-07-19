# Phase 6: Cross-sectional daily strategy track (scope)

> Scoped 2026-07-18 following the strategy diagnostics (see
> `DIAGNOSTICS-2026-07-18.md`). The diagnosed 1m intraday
> family is closed: every signal in the codebase produced ≲1bp gross per trade
> against a ≥3–5bp cost floor, and the three pre-registered redesign passes
> (multi_timeframe exits, overnight_reversal filters, momentum rescale) all
> failed in-sample before even reaching the fulltest gate. This phase pivots
> strategy research to the terrain the data asset actually supports:
> **daily-horizon, cross-sectional portfolios over the S&P 1500**, where
> per-trade moves (50–200bp) dwarf costs and 1,500 names give statistical
> power that 5 mega-caps never could.

## Ground rules (carried over, tightened)

- **Statistical gate = research layer, execution gate = fulltest.** Daily
  rank-portfolio strategies are deterministic enough to evaluate statistically
  in pandas (fills at recorded open/close prices, explicit cost sweep). The
  fulltest pipeline is impractical at 1500 symbols × daily rebalance and adds
  nothing statistically; its role here is **execution-fidelity validation** of
  any implemented survivor (reduced universe/window), not hypothesis testing.
- **Pre-registration is verifiable.** Phase B commits the hypothesis families,
  portfolio construction, cost model, and kill/advance rules to git **before**
  Phase C computes a single result. Selection rules bind; no post-hoc slicing.
- **One OOS shot** (2025-08-01 → 2026-02-01), frozen code and parameters, for
  whatever survives IS. Everything before it runs on IS only
  (2024-08-01 → 2025-08-01).
- **Long-only implementability constraint**: the OMS has no short support.
  Long-short deciles may be *measured* (they characterize the signal) but only
  long-side portfolios count toward advance/kill decisions unless we
  explicitly schedule OMS short work.

## Phases

### A. Data foundation (~half a day)
Build once, cache as parquet (small: ~1500 × ~378 days):
- Daily bars from 1m parquet with explicit session definitions: RTH open =
  first bar ≥09:30 ET, RTH close = last bar <16:00 ET, plus full-day
  OHLCV and overnight-gap fields. Extended-hours bars excluded from daily
  OHLC (they poisoned intraday diagnostics; sessions must be clean here).
- Universe hygiene report: per-symbol coverage (trading days present),
  liquidity (median daily dollar volume), obvious data pathologies. Output: a
  per-day eligible universe (coverage + liquidity floor, e.g. $5M/day median
  dollar volume) so thin names don't fabricate paper edge.
- **Survivorship quantification**: equal-weight eligible-universe return vs a
  cap-weighted benchmark proxy over the window — a numeric estimate of the
  drift the current-membership list bakes in, cited alongside every result.

### B. Pre-registration (~1–2h, committed before any Phase C run)
Three families, capped at three to bound multiple comparisons:
- **F1 Cross-sectional overnight reversal**: rank by intraday (open→close)
  return; long bottom decile at close, exit next open. Generalizes
  overnight_reversal from 5-name/threshold to 1500-name/rank form — the
  5-mega-cap failure does not test this (the documented effect concentrates
  in smaller names, which the 1500 partially covers).
- **F2 Short-term reversal**: rank by trailing 1–5 day return; long loser
  decile; 1–5 day hold. Higher turnover; cost sweep decides.
- **F3 Cross-sectional momentum**: rank by trailing 3–6 month return (skip
  most recent week); hold ~1 month. Costs negligible, but formation windows
  eat the IS year (≈12 usable months at 6m formation) and survivorship
  inflates this family the most — flagged, not fatal for IS screening.
To be frozen in the pre-reg doc: exact formation/holding grids (small, stated
up front), equal-weight construction, decile count, cost sweep {0, 2, 5,
10}bp/side, and the advance rule — positive long-side net at 5bp/side AND
sign-consistent in ≥3 of 4 IS quarters AND rank IC t-stat sanity; otherwise
kill. Benchmark: equal-weight eligible universe (separates selection from
beta).

### C. IS research (~1 day)
Run the frozen grid; report per family: daily rank IC (Spearman), decile
return monotonicity, long-side net across the cost sweep, turnover, quarterly
stability. Kill/advance strictly by the Phase B rule.

### D. OOS shot (hours)
Single frozen run for survivors. Survives → Phase E. Fails → track closes with
a written conclusion (as the 1m family closed today) and the honest residual:
18 months is one macro regime; a null here is a null for this window, not a
theorem.

### E. Conditional hardening + implementation (scoped only when needed)
1. **Point-in-time universe** (phase-4 optional iteration A, currently
   unapproved) — mandatory before any live decision on a survivor,
   especially F3.
2. Platform: daily-rebalance strategy interface (the `on_bar` per-symbol model
   doesn't fit rank portfolios), order timing near close/open, OMS short
   support only if a long-short variant is ever approved.
3. Fulltest execution validation on a reduced universe/window, then the
   live-paper route per ROADMAP.

## Expectations (stated so nobody re-reads this doc as a promise)
Best realistic outcome: one family survives OOS at realistic costs and earns a
live-paper trial plus a data-extension decision. The window is short (18
months, one regime), the OOS is one draw, and survivorship is unquantified
until Phase A. A clean triple-kill in Phase C/D is a fully acceptable outcome
and would close strategy research on this dataset with evidence.

## Phase A results (2026-07-19)

Landed as `src/axtrade/research/` (daily-bar builder, eligibility, hygiene +
survivorship reporting; 18 unit tests). Artifacts in `data/daily/` (untracked,
~36 MB — covered by `docs/data-backup.md`): `daily_bars.parquet` (541,134
rows, 1,446 symbols + SPY benchmark), `calendar.txt` (376 trading days,
2024-08-01 → 2026-01-30), `eligibility.parquet`, `hygiene_report.md`.

Key numbers:
- **Eligible universe** (63-day trailing window, ≥90% coverage, ≥$5M median
  RTH dollar volume, 21-day warmup): median 1,347/day, max 1,369 — the floors
  cut only ~5% of names. Warmup means no eligibility before 2024-09.
- **Survivorship/size drift**: EW eligible-universe total return +14.0% vs
  SPY +27.4% over the full period (spread −13.4%; IS year −13.8%, OOS half
  +1.7%). The naive expectation (survivorship inflates EW) is swamped by the
  size effect in this window — mega-caps led. The spread conflates
  survivorship + size and is NOT a clean survivorship estimate; the reason
  Phase B benchmarks against the **EW eligible universe itself** stands.
  Returns exclude dividends (split-adjusted-only data) on both legs.
- **The universe partially includes deaths/births**: 16 symbols have <90%
  full-period coverage — M&A delistings that ended mid-window (MRO, CTLT,
  DFS, JNPR, ANSS, PARA, WBA…) and late listings/spinoffs (AMTM, SARO,
  VSNT…). Coverage-gated eligibility handles both edges without look-ahead.
- **Sessions are clean**: 5 half-days detected (modal close 13:00 ET), zero
  zero-volume RTH days, late-open pathologies (601 symbol-days) concentrated
  in ultra-thin names (GHC) that the liquidity floor excludes anyway. The
  closing auction lands in the 16:00 ET bar — outside the doc's canonical
  RTH close — captured as `bar1600_close` (missing on only 0.4% of full
  symbol-days) so Phase B can pre-register either close definition.

**Data-integrity finding for Phase B (binding)**: split adjustment does not
cover spinoffs/special dividends. DD 2025-11-03 shows a −58.7% overnight gap
with flat dollar volume and doubled share volume — the Qnity spinoff, a fake
crash (holders were made whole). CORT 2025-12-31 (−50.4%, gap-only) is a
second suspect. Of 13 |cc_ret|>50% symbol-days, all are gap-dominated; most
are real news, at least one is a corporate action. **F1/F2 are long-loser
rules and would systematically buy fake spinoff crashes** — the Phase B
pre-reg MUST include a corporate-action guard (e.g. exclude formation
signals where the overnight gap exceeds a stated threshold, or an explicit
audited exclusion list of the 13), fixed before any Phase C run.

## Phase B results (2026-07-19)

Pre-registration frozen in [`phase6-preregistration.md`](phase6-preregistration.md)
(binding). Headline freezes: 3 primary cells = 3 binding tests (F1 single
cell; F2 primary J=5/H=5 of a 3×3 grid; F3 primary J=63 of {63,126}, skip-5,
21-day hold, overlapping tranches); entry conventions are implementable (F1
MOC via `bar1600_close` + MOO exit; F2/F3 next-open entry/exit); costs swept
{0,2,5,10}bp/side with 5bp binding; corporate-action guard = exclude
|gap_ret| > 25% within the formation lookback (covers the DD/CORT fake
crashes); advance = net>0 at 5bp AND gross > matched EW benchmark AND
positive in ≥(n−1) of n available quarters AND rank-IC |t| ≥ 2 — else kill,
no cell-switching. Next: Phase C implements and runs the frozen grid on IS.

## Phase C results (2026-07-19) — TRIPLE KILL, track closes

Engine landed as `src/axtrade/research/xsect.py` (26 unit tests on synthetic
frames: signal orientation, guard windows, entry/exit fallbacks, overlap
accounting, cost arithmetic, NW t-stats, advance-rule truth table,
no-look-ahead). One frozen IS run (6s wall clock), full report at
`data/research/is_report.md` (untracked). All 1,195 unit tests pass.

**Verdicts (primary cells, binding rule §8 of the pre-reg):**

| Family | net@5bp | gross vs EW bench | quarters | IC (NW t) | verdict |
|---|---|---|---|---|---|
| F1 overnight reversal | **−4.2% FAIL** | +20.6% vs +5.6% pass | 3/4 pass | +0.037 (t=+3.1) pass | **KILL** |
| F2 reversal J5/H5 | +6.4% pass | +11.4% vs +0.7% pass | 3/4 pass | **+0.013 (t=+0.8) FAIL** | **KILL** |
| F3 momentum J63 | **−9.4% FAIL** | −8.5% vs −5.4% **FAIL** | 2/3 pass | **−0.044 (t=−1.1) FAIL** | **KILL** |

**What the data actually said:**
- **F1 is a real signal that costs eat.** IC t=+3.1, monotone deciles, gross
  +20.6% over the IS year vs the EW-universe overnight drift of +5.6% — the
  ranking genuinely selects. But the construction trades 2 sides/day
  (~8.5bp/day gross vs a 10bp/day cost floor at the binding 5bp/side): net
  −4.2%. At 2bp/side it made +10.0%; the pre-registered gate was 5bp, and
  5bp is the honest number for MOC+MOO across ~135 names reaching down to
  $5M/day liquidity. Same shape as the 1m-family finding, one level up:
  signal real, gross-per-trade under the cost floor.
- **F2 is F1's echo, too weak to trust.** Positive net at the primary cell
  (+6.4%) but the signal itself doesn't clear sanity (IC t≈0.8 across the
  whole 3×3 grid, best cell t=1.6). The grid's positive cells are
  low-double-digit net returns riding a −15%-in-one-quarter drawdown
  profile. The rule killed it for exactly the pre-registered reason: a net
  P&L without a statistically detectable signal is selection noise.
- **F3 momentum is inverted in this window.** Long winners lost on every
  metric (J63 deciles: bottom +61bp/hold, top −112bp/hold; J126 same
  shape). 2024-11→2025-07 was a reversal regime (tariff crash + violent
  bounce); 3–6-month winners were exactly what mean-reverted. A one-regime
  18-month window cannot rehabilitate momentum, and the pre-reg forbids
  flipping the sign post-hoc.
- Consistent cross-family picture: every long-side portfolio craters in the
  2025-02→05 quarter and recovers after — the April-2025 whipsaw dominates
  the IS year. That is the "18 months is one macro regime" caveat from the
  scope doc made concrete.

**Track closure (per §D of this doc and §8 of the pre-reg):** no family
advances; the OOS half-year (2025-08→2026-02) stays untouched — usable as
virgin OOS by any future pre-registered cycle. Honest residuals: (1) F1's
overnight-reversal signal is real at this universe scale and would clear a
2bp cost world or a lower-turnover construction — either requires a NEW
pre-registered cycle, ideally on extended/point-in-time data, not a re-cut
of this one; (2) all numbers exclude dividends and ride current-membership
survivorship (quantified in Phase A); (3) F3's kill is regime-specific
evidence, not a theorem about momentum.

Strategy research on this dataset is now closed with evidence: the 1m
intraday family (2026-07-18 diagnostics) and the daily cross-sectional
family (this run) both die honestly. The platform track (live paper
validation, alert channels) is what remains.

## Relation to other tracks
- Platform track unchanged: live paper validation day (ROADMAP #3) still
  pending; alert channels (C1) queued behind it.
- Harness-realism P2s (P2-1..P2-6) stay parked — mostly irrelevant at daily
  horizon. P2-11 (regime degeneracy) irrelevant here; `oms.slippage_bps: 10`
  realism question is superseded by this track's explicit cost sweep.
