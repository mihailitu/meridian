# Appendix A — Short-horizon academic literature survey (1 min – 2 days)

> Deep-research thread output, 2026-08-29. Adversarially checked for replication
> failures and cost realism. Part of `docs/research-survey-2026-08.md`.

**Scope:** published/SSRN/credible-practitioner work, 2012–2026. Context: the
project's own falsification result (1–2bp gross/trade on 1-minute equity
signals vs a 3–5bp/side cost floor) is *consistent with the honest end of this
literature* — the papers that survive scrutiny all share one property: **few
trades per day in ultra-liquid instruments, with the edge per trade an order of
magnitude above the cost floor, or no edge at all.**

## Summary table (ranked by evidence strength × retail cost viability)

| # | Strategy | Horizon | Best net-of-cost evidence | Decay/replication status | Data needed | Retail verdict @1bp fut / 5bp eq |
|---|---|---|---|---|---|---|
| 1 | Crypto funding-rate carry (perp vs spot) | days–weeks (funding accrues 8h) | BIS: Sharpe 6.45 (2020–23) → **negative 2025**; academic CEX/DEX study net-positive | Real but decayed hard; crash risk (FTX-style) | funding-rate history + spot/perp prices (free APIs) | **Most viable class, but edge is compressing; operational risk ≫ market risk** |
| 2 | Market intraday momentum (first-½h → last-½h; Gao et al.) + hedging-demand variant (Baltussen et al.) | 30 min, 1 RT/day | Baltussen: significant across 60+ futures 1974–2020 incl. costs; Rosa (2022): **OOS predictability gone → data mining** | Contested: 16-country study says OOS-alive; US ETF version arguably dead | 1m or 30m bars (we have this) | **Marginal-plausible: 1 trade/day in ES fits a 1bp floor; edge itself is disputed** |
| 3 | Zarattini/Aziz/Barbon intraday momentum (SPY) & ES/NQ replication | intraday, ~1 trade/day | Indep. replication on ES net of $2.25/contract + 0.25-tick slip: **+2bp/trade, Sharpe 0.91** | Replicates directionally but weaker; flat 2010–2017; forward-test only | 1m bars | **Borderline: real but thin; works only because turnover is 1 RT/day in ES** |
| 4 | ORB QQQ / "Stocks in Play" ORB (Zarattini & Aziz) | intraday | Paper: 1,484% w/ zero slippage; replication: **break-even at ~2.2¢/share slippage**, 76% of filter PnL from 2022 | Partially debunked (regime artifact + no-slippage assumption) | 1m bars + pre-market volume/news for SIP | **Not viable as published; edge ≤ realistic slippage** |
| 5 | Overnight drift, index futures (Boyarchenko et al.) | hours (2–3am ET) | 3.6–3.7%/yr in one hour, 1998–2019, costs trivial (1 RT/day ES) | **Dead: ~0% since 2021 (NY Fed 2026 follow-up); NightShares ETFs closed** | hourly futures bars | **Was genuinely retail-viable; no longer exists** |
| 6 | Overnight vs intraday cross-section (Lou/Polk/Skouras; Lachance) | close→open daily | Lachance: SPY overnight **717% gross → −32% net**; cross-stock version worse | Pattern robustly real, robustly untradable | daily OHLC | **Not viable: daily RT in every position, cost floor ≫ per-night edge** |
| 7 | Post-news/earnings intraday drift | minutes–2 days | Drift exists mainly after *low-attention* announcements; HFT removes 65–100% of it | Being arbitraged away in real time | tick/1m + earnings timestamps | **Not viable at short horizon; residual PEAD is multi-day/small-cap (5bp+ spread names)** |
| 8 | Order-flow imbalance / LOB deep learning | seconds–minutes | CKS: linear OFI→price relation (descriptive); DeepLOB: profits at mid-price, **deteriorate to ~0 with spread** | Predictability replicated many times; *profitability* not, at taker cost | **L2/tick (we have neither); co-location for capture** | **Not viable retail: the alpha is smaller than the spread you cross to get it** |
| 9 | Intraday VWAP reversion / short-term reversal | minutes–hours | No credible published net-positive result at retail costs | Practitioner folklore; academic short-term reversal killed by costs | 1m bars | **Not viable; cost-dominated by construction (fades = high turnover, small edges)** |
| 10 | Sub-5-min OHLCV signals in index futures (MNQ) | 1–5 min | Mesfin (2026): 14 signal families, 5m MNQ 2021–25: **gross 0.07–1.5 pts/trade < 2-pt cost** | Systematic falsification — mirrors our result | 5m OHLCV | **Falsified. Independent confirmation of our own finding** |

## Detail sections

### 1. Crypto funding-rate carry / perp basis
- **Citations:** BIS Working Paper No. 1087, ["Crypto carry"](https://www.bis.org/publ/work1087.pdf) (Franz & Todorov); He, Manela, Ross, von Wachter, ["Fundamentals of Perpetual Futures"](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4301150); [CEX/DEX funding-rate arb risk/return study, Blockchain: Research & Applications 2025](https://www.sciencedirect.com/science/article/pii/S2096720925000818); Fan/Jiao/Lu/Tong, ["Risk and Return of Cryptocurrency Carry Trade"](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4666425).
- **Horizon/turnover:** position held days–weeks; funding accrues every 8h; turnover low (the *only* strategy class here where holding, not trading, earns the return).
- **Gross/net & cost assumptions:** BIS documents carry averaging >10%/yr (peaks >40%), funding-rate component ~8% mean at 0.8% vol; full-sample Sharpe 6.45 — falling to 4.06 from 2024 and **negative in 2025**. The CEX/DEX study reports up to 115.9%/6mo scenarios with max loss 1.92%, *net of exchange fees* (real taker fees ~2–5bp/side on majors, which the entry/exit round trip easily absorbs given weeks of accrual).
- **Replication:** the mechanism is arithmetic (you receive the funding print), so "replication" is about persistence, and persistence is failing: the BIS shows the edge compressing as institutional capital (post-ETF) arrives.
- **Data:** free — exchange funding-rate and price APIs.
- **Verdict:** *the only class where retail costs are structurally irrelevant; the risks are basis blowout, exchange/counterparty failure, and an edge that averaged ~0 in 2025. Viable as opportunistic yield, not as a standing alpha.*

### 2. Market intraday momentum (first-½h predicts last-½h)
- **Citations:** Gao, Han, Li, Zhou, [JFE 2018](https://www.sciencedirect.com/science/article/abs/pii/S0304405X18301351) ([SSRN 2440866](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2440866)); Baltussen, Da, Lammers, Martens, ["Hedging Demand and Market Intraday Momentum," JFE 2021](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3760365); **rebuttal:** Rosa, ["Understanding intraday momentum strategies," J. Futures Markets 2022](https://onlinelibrary.wiley.com/doi/abs/10.1002/fut.22375); **counter-rebuttal:** ["Intraday time series momentum: Global evidence," J. Financial Markets 2021](https://www.sciencedirect.com/science/article/abs/pii/S138641812100001X) (16 developed markets, in- and out-of-sample significant in 13).
- **Horizon/turnover:** 30-min hold, exactly 1 round trip/day, SPY/ES.
- **Gross/net & costs:** Gao et al. report OOS R²≈1.4% and economic gains but with light cost treatment (ETF spread ~1bp assumed). Baltussen et al. is the strongest version: 60+ futures, 1974–2020, last-30-min return predicted by rest-of-day, significant after (institutional, ~sub-1bp futures) costs, and reverts over following days — mechanism is gamma-hedging demand, a real structural flow.
- **Replication status:** genuinely contested. Rosa (2022) finds the US predictability **disappears out-of-sample and looks like data mining**; the 16-market study finds it alive internationally; QuantRocket-style leveraged-ETF implementations [flattened after ~2017](https://www.quantrocket.com/blog/leveraged-etf-intraday-momentum/).
- **Data:** 1m or 30m bars.
- **Verdict:** *the one equity-index anomaly whose turnover profile (1 RT/day, ES at ~1bp) fits the cost floor; the open question is whether the edge still exists at all — cheap to test directly on our own data before believing either camp.*

### 3. Zarattini/Aziz/Barbon "Beat the Market" (SPY) + ES/NQ replication
- **Citations:** [SSRN 4824172](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4824172) (2024); critical review at [QuantMacro Substack](https://quantmacro.substack.com/p/paper-review-an-effective-intraday); independent futures replication at [Quantitativo](https://www.quantitativo.com/p/intraday-momentum-for-es-and-nq).
- **Claims:** 2007–2024, SPY, "noise-band" trend entries + trailing stops: 1,985% total, 19.6%/yr, Sharpe 1.33 *claimed net of costs*; execution-timing and fill assumptions not fully disclosed (reviewer's main criticism), single instrument, authors run a firm marketing to day traders (incentive flag).
- **Replication:** the Quantitativo ES replication with explicit retail costs ($0.85 commission + $1.40 fees/contract + 0.25-tick slippage) gets **8.1%/yr, Sharpe 0.91, +2bp expected/trade, 36% win rate** — directionally confirms but well below the paper, was flat 2010–2017, and is only in forward-test. A follow-up ([Maróy, SSRN 5095349](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5095349)) "improves" it to Sharpe >3 via parameter optimization — a data-mining red flag, not a validation.
- **Data:** 1m bars.
- **Verdict:** *plausibly a real but thin edge (~2bp/trade) that survives only because ES costs ~1bp and it trades once a day; on equities at 5bp/side it dies — the per-trade edge equals what we measured on our own strategies.*

### 4. Opening Range Breakout (QQQ; Stocks in Play)
- **Citations:** Zarattini & Aziz, ["Can Day Trading Really Be Profitable?" SSRN 4416622](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4416622) (5-min ORB on QQQ, 2016–2023, 1,484% vs 169% B&H); Zarattini, Barbon & Aziz, ["A Profitable Day Trading Strategy For The U.S. Equity Market"](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284) (ORB on "Stocks in Play" — high relative-volume names — Sharpe 2.4 claimed, $0.0005/share commission, **zero slippage**).
- **Rebuttals:** [independent replication (Brusco, GitHub)](https://github.com/giovannibrusco/zarattini-2023-orb-qqq): break-even at ~2.2¢/share slippage vs QQQ's ~1¢ spread; NQ-filter PnL 76% from 2022 alone; 9,350% variant is a parameter search. [QuantConnect replication](https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/) and [danfin.net's survey](https://danfin.net/opening-range-breakout-research) both flag leverage + no-slippage as load-bearing. The [MNQ falsification study](https://arxiv.org/abs/2605.04004) finds ORB variants ≈ 0 on futures.
- **Verdict:** *not viable as published — the claimed edge sits inside realistic slippage and one regime (2022); the stocks-in-play version trades exactly the names where a 5bp/side floor is optimistic.*

### 5. Overnight drift (index futures, European open)
- **Citations:** Boyarchenko, Larsen, Whelan, ["The Overnight Drift," NY Fed Staff Report 917](https://www.newyorkfed.org/research/staff_reports/sr917) / RFS 2023; follow-up ["The Disappearing Overnight Drift," Liberty Street Economics, July 2026](https://libertystreeteconomics.newyorkfed.org/2026/07/the-disappearing-overnight-drift/).
- **Numbers:** 1998–2019, ES futures 2–3am ET earned ~3.6–3.7%/yr — ~60% of ES's total close-to-close return — driven by dealer inventory unwind after closing order imbalances; costs trivial (one ES round trip ≈ 0.8bp). **Since 2021: ~zero**, because closing order-imbalance dispersion halved (6.5%→2.9%). NightShares ETFs built on the sibling anomaly closed within 14 months.
- **Verdict:** *the best-documented retail-executable anomaly of the last decade — and the cleanest example of one dying; a case study in decay, not a strategy.*

### 6. Overnight vs intraday return decomposition (cross-sectional "night returns")
- **Citations:** Lou, Polk, Skouras, ["A Tug of War," JFE 2019](https://www.sciencedirect.com/science/article/abs/pii/S0304405X19300650); Lachance, ["Night trading: lower risk but higher returns?" RFE 2023](https://onlinelibrary.wiley.com/doi/full/10.1002/rfe.1180); [Alpha Architect summary](https://alphaarchitect.com/trading-costs-wipe-out-the-overnight-return-anomaly/).
- **Net numbers:** SPY 1993–2020 overnight-only: **717% gross → −32% net** at realistic retail costs. Cross-sectional versions require a daily round trip in *every* stock — hundreds of bp of annual cost drag against per-night edges of a few bp.
- **Replication:** the *pattern* replicates everywhere; the *strategy* has never been shown net-positive. Elm Wealth's sympathetic ["Night Moves" analysis](https://elmwealth.com/night-moves-overnight-drift/) concedes it needed institutional costs plus leverage.
- **Verdict:** *definitively untradable at retail; useful only as a conditioning variable (don't pay the spread to hold intraday what earns its return overnight).*

### 7. Post-news / earnings intraday drift
- **Citations:** Lyle, Stephan, Yohn, ["Processing Time and the Speed of the Market Response to Earnings"](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3064160); Chakrabarty, Moulton, Wang, [JFM 2021](https://www.sciencedirect.com/science/article/abs/pii/S138641812100063X): **HFT removes 65–100% of post-announcement inefficiency** in low-attention names; [Quantpedia PEAD entry](https://quantpedia.com/strategies/post-earnings-announcement-effect).
- **Verdict:** *the minutes-scale drift is exactly where HFT competes hardest; the residual drift lives at 1–4 days in small, high-spread names where realistic cost is >5bp/side. Data: 1m bars + accurate announcement timestamps (non-trivial to source cleanly).*

### 8. Order-flow imbalance / microstructure alpha
- **Citations:** Cont, Kukanov, Stoikov, ["The Price Impact of Order Book Events" (2014)](https://arxiv.org/pdf/1011.6402); [generalized OFI (2021)](https://arxiv.org/pdf/2112.02947); Zhang, Zohren, Roberts, [DeepLOB (2019)](https://arxiv.org/abs/1808.03668); ["Deep LOB trading: Half a second please!"](https://www.sciencedirect.com/science/article/abs/pii/S0957417422019170); [microstructural critique of deep LOB forecasting](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12315853/).
- **Honest read:** OFI→price predictability is the *most replicated* finding in this survey (linear, stable across stocks and timescales). But every profitability demonstration assumes mid-price fills / zero fees; the critique literature shows performance "deteriorates" to ~nothing once you pay the spread, and capture requires maker-side execution + latency competitiveness. Data requirement is L2/tick, not a 1m parquet archive.
- **Verdict:** *real alpha, wrong customer: it IS the spread — you can only harvest it by being the market maker. Zero retail viability.*

### 9. Intraday reversal / VWAP reversion
No credible academic paper demonstrates net-positive VWAP-reversion returns; the space is practitioner blogs. Academic short-term reversal (weekly/daily) is a cost casualty in every serious treatment, and the [MDPI KOSPI intraday-momentum-with-costs study](https://www.mdpi.com/1911-8074/15/11/523) shows effective-spread proxies erase most intraday timing value. *Verdict: cost-dominated by construction.*

### 10. 1–5 minute futures signals (ES/NQ/MNQ) — direct evidence
- **Citation:** Mesfin, ["Structural Limits of OHLCV-Based Intraday Signals in MNQ Futures: A Systematic Falsification Study" (arXiv 2605.04004, 2026)](https://arxiv.org/abs/2605.04004): 14 signal families (momentum, gap continuation, session effects), 947 days of 5-min MNQ, 2-point round-trip cost: gross edges of **0.07–1.5 pts/trade — below cost — across the board**; only two session-timing signals passed pre-registered validation gates.
- **Verdict:** *an independent, pre-registered confirmation of our own result: at the 1–5 minute horizon, OHLCV bars simply don't contain more alpha than the friction.*

## Cross-cutting conclusions

1. **The survivors all minimize trades, not maximize them.** Everything net-positive in this survey trades ≤1 round trip/day in an instrument costing ≤1bp (ES intraday momentum, overnight drift while it lived) or earns by *holding* (crypto carry). Nothing at 1-minute frequency survives anywhere, for anyone, in any published net-of-cost test.
2. **Publication is a death sentence for capacity-constrained timing anomalies.** Overnight drift died ~2 years after the Fed paper; leveraged-ETF intraday momentum flattened post-2017; crypto carry's Sharpe went 6.45 → negative after the ETF era began. Assume any 2023–2024 Concretum-style paper is already being arbitraged.
3. **Data-mining flags concentrate in the retail-marketed papers** (Zarattini et al.: parameter searches, zero-slippage, single instruments, commercial incentive), while the sober papers (Rosa 2022, Lachance 2023, Mesfin 2026, NY Fed 2026) are uniformly negative. The genre split is itself informative.
4. **For this project specifically:** the only two literature-supported tests worth the existing 1-minute archive are (a) the Gao/Baltussen last-half-hour effect on index products — one trade/day, disputed but cheap to check, and mechanically linked to a real flow (gamma hedging); and (b) an ES/MES variant of the Zarattini replication at IBKR retail costs — with the prior that the honest replication found +2bp/trade, i.e., exactly the edge size we already know sits at our cost floor. Anything requiring L2, latency, or per-stock daily round trips is out of reach by construction, not by effort.
