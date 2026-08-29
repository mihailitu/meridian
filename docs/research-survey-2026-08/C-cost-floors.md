# Appendix C — Retail cost-floor and venue analysis: is 1–2 minute trading mathematically viable?

> Deep-research thread output, 2026-08-29. Part of `docs/research-survey-2026-08.md`.
> All prices/levels as of late Aug 2026: SPX ≈ 7,677, NDX ≈ 29,077, gold ≈ $4,343/oz,
> WTI ≈ $83–86, EUR/USD ≈ 1.161.

## 1. Fee inputs (verified, low-volume retail tier)

**US equities, IBKR Pro (no PFOF on Pro SmartRouting; Lite is US-only anyway).** Tiered: $0.0035/share, $0.35 min, plus exchange/clearing pass-throughs; Fixed: $0.005/share, $1 min ([IBKR pricing](https://www.interactivebrokers.com/en/pricing/commissions-stocks.php)). Regulatory: SEC Section 31 fee **$20.60/million (0.206bp), sells only, effective 2026-04-04** (it was $0.00 for the prior fiscal period) ([SEC advisory](https://www.sec.gov/rules-regulations/fee-rate-advisories/2026-2)); FINRA TAF **$0.000195/share on sells, cap $9.79, since 2026-01-01** ([FINRA TAF](https://www.finra.org/rules-guidance/guidance/trading-activity-fee)).

**CME futures, IBKR fixed.** ES: $0.85 commission + $1.38 exchange fee = **$2.24/side**; micros: $0.25 commission + $0.35 exchange (MES/MNQ) + $0.01 NFA ([IBKR futures commissions](https://www.interactivebrokers.com/en/pricing/commissions-futures.php), [TradeStation exchange-fee table](https://www.tradestation.com/pricing/exchange-execution-and-clearing-fees/)). Other exchange fees/side: GC $1.65, CL $1.50, MCL $0.50, M6E $0.24, MGC $1.10 (⚠ AMP's Feb-2025 notice says $0.60 — range used). **⚠ Unverified:** ZN (~$0.85–0.90) and 6E (~$1.60) exchange fees. CME amended fees 2026-04-01 ([SER-9676](https://www.cmegroup.com/notices/ser/2026/02/ser-9676.html)); verify against the [CME fee finder](https://www.cmegroup.com/company/clearing-fees/fee-finder.html) before trusting to a tenth of a bp.

**FX.** IDEALPRO: 0.20bp commission, **$2.00 min/order**; EUR/USD spread ~0.1–0.2 pip ([IBKR forex PDF](https://www.interactivebrokers.com/download/newMark/PDFs/commissionsForex.pdf)).

**Crypto.** Binance spot base 10/10bp maker/taker (7.5 with BNB); USDT-perp **2bp maker / 5bp taker**, funding baseline ~0.01%/8h — irrelevant at minute holds. Kraken Pro base 25/40bp; Coinbase Advanced base 40/60bp. IBKR crypto (Paxos/Zero Hash): 12–18bp, $1.75 min ([IBKR crypto pricing](https://www.interactivebrokers.com/en/pricing/commissions-cryptocurrencies.php)).

## 2. Round-trip cost table

Notionals: ES ≈ $384k (50×SPX), MES ≈ $38.4k, NQ ≈ $582k, MNQ ≈ $58.2k, GC ≈ $434k, MGC ≈ $43.4k, CL ≈ $84k, MCL ≈ $8.4k, 6E ≈ $145k, M6E ≈ $14.5k, ZN ≈ $112k. Tick-to-bp: ES/MES tick 0.25pt = 0.33bp; NQ/MNQ 0.25pt = 0.086bp; GC/MGC $0.10 = 0.23bp; CL/MCL $0.01 = 1.19bp; 6E 0.00005 = 0.43bp; M6E 0.0001 = 0.86bp; ZN ½/32 = 1.4bp. Spread cost/side = half typical quoted spread; slippage = estimate for small retail size crossing at signal time (⚠ estimates, not measurements — our own 3–5bp/side equity measurement is the gold standard for equities).

| Venue / instrument | Comm+reg RT (bp) | Half-spread /side (bp) | Slippage /side (bp) | **RT total (bp)** | Edge @ break-even / @2× |
|---|---|---|---|---|---|
| US mega-cap stock (AAPL-class), IBKR Pro | 0.5–0.7 | 0.5–1 | 0.5–1.5 | **2.5–5** (ours measured: **6–10**) | 6–10 / 12–20 |
| US mid-cap stock | 0.5–0.8 | 2.5–5 | 1–3 | **8–17** | 8–17 / 16–34 |
| **ES** (E-mini S&P) | 0.12 | 0.16 | 0–0.15 | **0.45–0.75** | 0.5–0.75 / 1–1.5 |
| **NQ** | 0.08 | 0.09–0.17 | 0.05–0.15 | **0.35–0.7** | ~0.5 / ~1 |
| **MES** | 0.32 | 0.16 | 0–0.15 | **0.65–0.95** | ~0.8 / ~1.6 |
| **MNQ** | 0.21 | 0.09–0.17 | 0.05–0.2 | **0.5–0.95** | ~0.7 / ~1.5 |
| ZN (10-yr note) ⚠fee est. | ~0.31 | 0.7 | 0–0.3 | **1.7–2.3** | ~2 / ~4 |
| GC (gold) | 0.12 | 0.12–0.23 | 0.1–0.25 | **0.5–1.1** | ~0.8 / ~1.6 |
| MGC ⚠fee range | 0.4–0.63 | 0.12–0.35 | 0.1–0.4 | **0.9–2.1** | ~1.5 / ~3 |
| CL (WTI) | 0.56 | 0.6 | 0.3–0.6 | **2.3–3** | ~2.6 / ~5 |
| MCL | 1.8 | 0.6–1.8 | 0.6–1.8 | **4.2–9** | ~6 / ~12 |
| 6E ⚠fee est. | 0.34 | 0.22 | 0–0.2 | **0.8–1.2** | ~1 / ~2 |
| M6E | 0.69 | 0.43 | 0.2–0.4 | **1.9–2.6** | ~2.2 / ~4.4 |
| IDEALPRO EUR/USD ($100k clip) | 0.4 | 0.05–0.1 | 0.05–0.15 | **0.6–0.9** | ~0.7 / ~1.5 |
| Binance BTC perp, taker both sides | 10 | 0.1–0.5 | 0.2–1 | **10.6–13** | ~12 / ~24 |
| Binance BTC perp, maker both sides | 4 | (earn spread, but see §4) | — | **~4 + adverse sel.** | ~5 / ~10 |
| Binance spot BTC (taker) | 20 (15 w/BNB) | 0.1–0.5 | 0.2–1 | **20.6–23** | ~21 / ~42 |
| Kraken Pro / Coinbase Adv. spot (taker) | 80 / 120 | 0.5–2 | 0.5–2 | **82–126** | hopeless |
| IBKR crypto (Paxos/ZH) | 24–36 | 1–3 | 1–3 | **28–48** | hopeless |
| Index CFDs (EU retail) | 0 comm typical | spread ≥ 2–5× futures + overnight financing | — | **≥2–5× ES** | dominated by futures |

CFD verification: current sources confirm CFD spreads are "almost always wider than those on a centralized exchange" and futures are typically tighter like-for-like ([BrokerChooser](https://brokerchooser.com/education/options-and-futures/futures-vs-cfd), [ActivTrades](https://www.activtrades.com/en/news/contract-for-difference-vs-futures-key-trading-differences)). CFDs do **not** rescue the math — they remove the visible commission and hide a bigger spread.

**EU-retail notes:** PRIIPs blocks US ETFs (SPY/QQQ) for retail — no KID, no sale ([justETF](https://www.justetf.com/en/news/etf/us-domiciled-etfs.html)); single US stocks are fine (shares aren't PRIIPs). CME futures and micros **are** available to IBKR Ireland retail (KIDs provided; [IBKR IE futures](https://www.interactivebrokers.ie/en/trading/products-futures.php)). The interesting venues in this table are all actually accessible.

## 3. Annual gross alpha needed just to pay costs

Cost drag ≈ N trades/day × RT × 252, as % of the notional deployed per trade:

| Venue (RT bp) | 5/day | 10/day | 30/day |
|---|---|---|---|
| ES (0.55) | 6.9%/yr | 13.9% | 41.6% |
| MES (0.8) | 10.1% | 20.2% | 60% |
| US mega-cap at our measured 8bp | 101% | 202% | 605% |
| Binance perp taker (11) | 139% | 277% | 832% |

At our measured equity floor, ten 1-minute trades a day must generate >200% annualized gross on deployed notional before a cent of profit. On ES the same activity needs ~14% — orders of magnitude apart. The drag is in % of *per-trade notional*; with futures leverage the drag on *account equity* is proportionally larger.

## 4. Adverse selection at 1–2 minute horizons

The credible evidence says minute-scale liquidity provision by slow traders is structurally negative-EV, and minute-scale liquidity *taking* pays more than the quoted spread suggests:

- **Aquilina, Budish & O'Neill (QJE 2022, FCA data):** latency-arbitrage races occur ~once per minute per FTSE-100 symbol, constitute ~20% of volume and ~⅓ of effective spread/price impact, an ≈**0.5bp tax on all trading**; a resting order at a stale price after any 1-minute-scale price move is picked off in 5–10 microseconds ([QJE](https://academic.oup.com/qje/article/137/1/493/6368348), [NBER w29011](https://www.nber.org/papers/w29011)). A retail limit order *is* the stale quote in that race, every time.
- **SEC HFT literature review:** realized spreads (what a liquidity provider actually keeps after adverse selection) are near zero or negative at short horizons; when price impact exceeds effective spread, passive fills lose on average ([SEC](https://www.sec.gov/marketstructure/research/hft_lit_review_march_2014.pdf)). Fast liquidity suppliers survive on speed + rebates retail doesn't have ([Hoffmann, JFE 2014](https://www.sciencedirect.com/science/article/abs/pii/S0304405X14000610)).
- **Fill asymmetry:** a retail limit order at minute scale fills preferentially when the market blows through it (filled and wrong) and misses when the signal was right (price runs away). Internalizers absorb benign flow; lit resting orders interact disproportionately with informed flow ([CFA Institute](https://blogs.cfainstitute.org/marketintegrity/2014/12/18/hft-price-improvement-adverse-selection-an-expensive-way-to-get-tighter-spreads/)).
- **Market orders:** effective spread ≥ quoted at exactly the moments a momentum-style signal fires, because spreads widen and depth thins on the news/volatility that generated the signal. Our own 3–5bp/side measurement — versus ~1–2bp "quoted" arithmetic for large caps — is itself evidence of this gap.

Practical translation: "go passive to save the spread" does not work at this horizon; assume taker costs, and add ~0.5bp of structural adverse-selection tax even then.

## 5. Verdict: horizon math and venue ranking

Alpha available scales roughly with horizon volatility (√t): with SPX daily σ ≈ 100bp, per-trade σ is ~**5bp at 1 min, ~20bp at 15 min, ~40bp at 1h, ~100bp at 1 day**. A genuinely good retail signal captures maybe 5–20% of horizon σ gross, i.e. **~0.3–1bp at 1–2 min**, 1–4bp at 15 min, 2–8bp at 1h, 5–20bp at 1 day.

| Horizon | Plausible gross edge | ES RT 0.55bp | Equities RT 8bp |
|---|---|---|---|
| 1–2 min | 0.3–1bp | costs eat 55–180% of edge | costs 8–27× edge |
| 15 min | 1–4bp | 14–55% | 2–8× edge |
| 1 hour | 2–8bp | 7–27% | 1–4× edge |
| 1 day | 5–20bp | 3–11% | 40–160% |

**Ranking for a 1–2 minute strategy:** 1) **ES/NQ** (~0.35–0.75bp RT) — the only venue where the math is even arguable; 2) **MES/MNQ** (~0.5–1bp) — same market, 10× smaller size, ~1.5× the friction; 3) GC, IDEALPRO EUR/USD, 6E (~0.5–1.2bp, but FX per-minute σ is only ~1–1.5bp, so edge-to-cost is worse than it looks); 4) ZN, M6E, CL (~2–3bp) — tick size alone kills it; 5) US single stocks at measured 6–10bp RT — falsified, correctly; 6) crypto perps (~4bp maker-only with severe adverse selection, 10bp+ taker); 7) spot crypto, IBKR crypto, CFDs — 20–120bp, not a serious conversation.

**The honest bottom line.** No retail venue gets below ~1–2bp round trip *except* CME equity index futures, and ES sits at ~0.5bp only because you cross a 0.33bp tick — the exchange fee floor plus one tick is irreducible without member rates and co-location. Against ~0.3–1bp of realistically capturable minute-scale alpha, ES at break-even leaves nothing at 2× costs, and everything smaller (MES, at our capital scale) is already at parity with the *entire* plausible edge. So: 1–2 minute trading is **mathematically visible but not practically viable** for retail — the one venue that clears the arithmetic bar demands capturing essentially 100% of a top-decile signal, gross, forever, in the most latency-competitive instrument on earth (0.5bp of which is confiscated by the arms race per Aquilina-Budish-O'Neill). The equity falsification at 3–5bp/side was not a strategy failure; it was the market telling the truth about the venue. The math turns benign at 15-min+ in index futures (costs 15–50% of edge) and at 1-day even in single stocks. If minute-scale signals exist in our research, the rational uses are (a) as *entry-timing overlays* on longer-horizon positions, where they pay costs already being incurred, or (b) rescaled to 15-min+ holding periods on ES/MES — not as standalone 1–2 minute round trips.

**Unverified/flagged:** ZN (~$0.87) and 6E (~$1.60) exchange fees; MGC fee ($0.60 vs $1.10 conflicting sources); all slippage figures are modeled, not measured; CME's 2026-04-01 amendment should be checked against the fee finder before building on the futures numbers; futures spread-in-ticks figures are conventional wisdom, not a current depth-of-book measurement — worth one day of our own tick data on MES before any commitment.
