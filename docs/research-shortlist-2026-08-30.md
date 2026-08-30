# Deep research — what to build next (2026-08-30)

Status: RESEARCH SYNTHESIS, not a pre-registration; no IS run may happen off
this document. Extends `docs/research-survey-2026-08.md` (which closed the
sub-15-minute question) and `docs/research-new-asset-classes.md` (T1 scoping).
Question: which strategies with published out-of-sample evidence clear our
constraints (daily+ horizon, low turnover, €20–100k, IBKR) and deserve a
pre-registered test?

Method note: multi-agent deep-research run (4 threads, 21 sources, 95 raw
claims). Claims below marked **[3-0]** survived three-vote adversarial
verification, **[2-0]** two votes, **[mv]** manually verified against the
source, **[uv]** extracted but unverified (the run hit a usage limit before
voting) — weight accordingly.

## Base rate for everything below: publication decay

- Across 97 published cross-sectional predictors, post-publication returns
  decline ~26–58% depending on version; both "no change" and "zero alpha
  post-publication" are statistically rejected — a haircut, not a death
  sentence (McLean & Pontiff). **[3-0]**
- The haircut is largest where arbitrage is cheapest: large-cap, liquid,
  low-idiosyncratic-risk names — index-level effects should be presumed
  *more* decayed than costly-to-arbitrage ones. **[3-0]**
- US long/short anomaly returns decline ~60–65% post-publication (~36% after
  sample end); the US is the only market of 39 with reliable post-publication
  decay (Jacobs & Müller, JFE 2020). **[2-0]**/[uv]
- Factor alpha decay may have *accelerated* post-2015 beyond crowding-model
  predictions, correlated with ETF asset growth. **[uv]**

Planning rule adopted: assume any published US effect retains ~35–40% of its
in-sample magnitude.

## Thread 1 — Pre-FOMC drift (feeds E1): alive only conditionally

The literature splits, and the split is informative:

- Unconditional drift is gone in the extended academic sample: L&M's 49bp
  (1994–2011) fell to ~44bp (2011–2015) then ~9bp (2016–2019), difference
  significant at 1% (SSRN 3134546). Authors attribute it to *reduced
  monetary-policy uncertainty* (no VIX drop on announcement days post-ZLB),
  not crowding. **[3-0]**
- The drift is concentrated in high-uncertainty regimes: **109bp when
  implied vol is above its prior median vs 9.7bp below; ~zero or negative in
  the lowest IV quintile** (Martello & Ribeiro, "Pre-FOMC Announcement
  Relief", SSRN 3286745). Mechanism: implied variance resolves 103.5bp into
  the announcement in high-vol periods, ~0 in low-vol — a risk-premium
  (relief) story that *predicts* the 2016–2019 disappearance (low-VIX era)
  rather than contradicting it. **[mv]**
- A practitioner replication on SPY through Dec 2024 (QuantSeeker) finds the
  strategy remained profitable post-publication: flat 2016–2019, recovered
  after; now concentrated in press-conference meetings; simple retail
  implementation (close t−1 → close t, 5bp one-way, 8 trades/yr) ≈ 4% CAGR,
  Sharpe 0.5–0.6 since 1993. **[uv]**

**Verdict:** consistent with our own Q3 result (+21.5bp/meeting, t=2.31,
right-skewed). The unconditional rule is weak in calm regimes; the
VIX-conditional version is the defensible object. **Implication for E1's
pre-registration: pre-specify a VIX/implied-vol conditioning analysis (or
conditional sizing) and robust statistics — not an always-on rule.** At 8
events/yr it costs nothing to run alongside anything else; it is a satellite,
not a core strategy.

## Thread 2 — PEAD / earnings: do not build (risk management only)

- Classic PEAD has decayed — a March 2026 JAAF paper (Griffin, McInnis &
  Zhao) takes the decline as its premise. **[3-0]**
- Costs eat what remains: PEAD abnormal returns concentrate in the
  highest-transaction-cost names; net of costs the strategy is uneconomical
  for most participants (Ng, Rusticus & Verdi). **[3-0]**
- The immediate reaction is machine-speed: post-2016, a post-announcement
  strategy is insignificant once bid-ask spreads are included; delaying entry
  5 seconds cuts returns to 0.41%/trade, beyond that insignificant (arXiv
  2601.08962). **[3-0]**
- Earnings announcements trigger after-hours jumps with >90% probability vs
  ~3% baseline — independent corroboration of our Q4 finding that earnings
  days are a distinct single-name tail-risk regime. **[3-0]**
- The PEAD-*reversal* variant (Milian) is high-turnover (daily rebalance,
  ~4 names, 2-day holds), had a −93% max drawdown in its own backtest, and
  Quantpedia's own OOS tracking is slightly negative. **[uv]**

**Verdict:** matches E4/Q4's conclusion exactly. Earnings knowledge is worth
encoding as **risk management** (size down / stand aside with a report due —
p90 move 10% vs 3.3%), not as a return strategy. Closes the earnings thread.

## Thread 3 — Futures trend following (T1): strongest candidate, with strict conditions

Evidence the edge survives — but only in a specific corner:

- Short-term trend died post-2008/09 and the damage scales with signal
  speed: 5d Sharpe 0.84→0.12, 10d 0.83→0.22, 20d 0.79→0.27, **50d only
  0.70→0.40**. Slow signals are the surviving zone. **[3-0]**
- The collapse concentrates in small-tick contracts (Sharpe → ~0);
  **large-tick contracts retained Sharpe ~1.0–1.2** — contract selection
  matters as much as signal speed. **[3-0]**
- The decay is signal degradation, not costs: a zero-lag execution test does
  not restore post-2008 performance, and crowding is rejected (impact drag
  ~0.1 Sharpe at 1% participation; CTA AUM timing doesn't fit). A cheap
  retail implementation cannot rescue *fast* trend. **[uv]**
- Canonical TSMOM (Moskowitz-Ooi-Pedersen 2012: Sharpe 1.31, 1965–2009,
  monthly rebalance, 12m lookback, vol-scaled) is in-sample only; regime
  honesty from a 62-market practitioner replication: ~Sharpe 2.1 in the
  1990s vs ~1.0 gross over 1995–2026, max DD 23%. Costs are genuinely small
  at this speed: 6–10x/yr turnover ≈ 30–50bp/yr drag. **[uv]**

Small-account feasibility (Rob Carver, qoppac): **[uv]**

- ~$2.5–5k/instrument floor; whole-contract rounding costs ~20% of Sharpe at
  1-contract max, ~5% at 2; diversification drives the published results
  (Sharpe ~0.35 one instrument → ~0.61 at eight → ~0.70 at 37); ~$100k for
  an 8-instrument one-per-asset-class book (pre-micros arithmetic).
- At $25k across 20 instruments, conventional sizing breaks down without
  micro contracts; a 10-contract elastic-net replica of a 62-market program
  reached Sharpe 0.84 with 0.68 tracking correlation — most of a diversified
  program is recoverable from few contracts *if selected carefully*.

**Verdict: corroborates the T1 pick.** Build shape: slow signals (≥50d /
multi-lookback average), micro contracts for breadth at our capital,
large-tick contract preference, vol-targeted, weekly-to-monthly rebalance.
Honest expectation after the decay haircut: **net Sharpe ~0.3–0.5, deep
multi-year drawdowns** — a diversifier with positive expectancy and equity
tail-hedge properties (TSMOM does best in extreme equity moves), not a
get-rich engine.

## Thread 4 — Other candidates: mostly dead or too small

- **Overnight drift**: real historically (1995–2022 index returns ~all
  overnight; single-stock long/short 38%/yr gross, t≈17) but decayed since
  the 2008–2015 papers, and killed by tiny costs — at 1bp/trade the
  long/short made nothing in its last 8 years; authors' retail advice is
  "trade less", not "trade the close" (Elm Wealth). **[uv]** Skip.
- **Index reconstitution**: discretionary S&P 500 deletions beat additions
  by 22% over the following year (FAJ 2023) **[3-0]**, but portfolio-level
  capturable alpha is ~23bp/yr — tracking-improvement sized, not a
  standalone strategy **[3-0]**. Skip as a build; a concentrated
  long-deletions tilt could be scoped later as a portfolio overlay, not a
  system.
- **Crowding signals**: timing factors by crowding earns nothing (Sharpe
  0.22 vs 0.39 benchmark); crowding predicts *crash risk*, not returns —
  usable only as a risk overlay. **[uv]**

## Shortlist (ranked)

1. **T1 — slow futures trend following with micros** (build): the only
   candidate with surviving post-publication evidence, costs that fit the
   speed, and a capital path at €20–100k. Proceed to T1 spec →
   pre-registration. Design constraints from the evidence: ≥50d signals,
   large-tick contract selection, breadth via micros before cleverness,
   expect Sharpe 0.3–0.5 net.
2. **E1 — pre-FOMC, VIX-conditional** (already in flight): keep, but the
   pre-registration must encode the conditioning insight; ~8 events/yr,
   satellite-sized.
3. **Earnings-day risk overlay** (small, free): encode Q4 as position-sizing
   rules in existing/future single-name strategies. Not a strategy; a
   guardrail.

**Not building:** PEAD (any variant), overnight effects, index
reconstitution standalone, short-term futures trend, crowding-as-signal.

## Sources (21)

SSRN 3134546 (pre-FOMC disappearance); Quantpedia pre-FOMC/high-uncertainty
(Martello & Ribeiro SSRN 3286745); QuantSeeker "Trading the Fed";
UCLA Anderson Review PEAD; Griffin-McInnis-Zhao JAAF 2026; Ng-Rusticus-Verdi
(JAR 2008); arXiv 2601.08962 (earnings jumps/decay); arXiv 2607.01550
(trend-following decay by tick size); qoppac (Carver, small-account
diversification ×2); Alpha Architect TSMOM; Quantpedia TSMOM; Beyond Passive
(62-market replication); Elm Wealth overnight ×2; Quantpedia PEAD-reversal;
McLean & Pontiff; Jacobs & Müller JFE 2020; FAJ 2023 index deletions;
microalphas factor decay; arXiv 2512.11913 (post-2015 alpha decay).
