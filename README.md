# meridian (package: `axtrade`)

An event-driven algorithmic trading platform in Python, built as a research-first project:
real-time ingestion from IBKR / Alpaca / Yahoo, bar aggregation and indicators, a multi-strategy
runner with paper-trading OMS, a full-pipeline historical replay harness, and an offline
cross-sectional research layer. A FastAPI + React dashboard sits on top.

The honest headline: after seven phases of pre-registered strategy research on an 18-month,
S&P 1500, 1-minute dataset, no strategy cleared the in-sample / out-of-sample gate after costs.
The platform, the audits, and the harness are the deliverable. See `ROADMAP.md` and
`docs/AUDIT-*.md` for the full record, including the five accounting and data-layer bugs the
harness caught in its own backtests before any strategy result was trusted.

## Architecture

```
Gateway -> Redis (ticks) -> Aggregator -> Redis (bars) + TimescaleDB
                                |                |
                          IndicatorEngine        v
                                           StrategyRunner -> OrderManager -> PostgreSQL
                                                |                             (positions,
                                           [Strategies]                        orders, fills)
```

- `gateway/`: `DataAdapter` implementations for Mock, IBKR (`ib_insync`), Alpaca, Yahoo;
  dynamic symbol subscription over Redis pubsub.
- `aggregator/`: tick-to-OHLCV bar engine, `IndicatorEngine` (SMA, RSI, Bollinger, ATR,
  regime), TimescaleDB persistence.
- `strategies/`: `BaseStrategy` with `momentum`, `mean_reversion`, `multi_timeframe`, `pairs`,
  `discovery_momentum`, `overnight_reversal`, and a `buy_hold` calibration benchmark whose
  result is computable by hand.
- `oms/`: order lifecycle, `PaperBroker` / `IBKRBroker`, `RiskManager`, position sizing
  (fixed, risk-pct, Kelly, ATR), portfolio risk.
- `fulltest/`: replays parquet history through the real gateway, aggregator, strategy runner,
  and discovery services in-process against an isolated Redis DB and TimescaleDB; IS/OOS
  comparison reports.
- `research/`: offline pandas layer over the 1-minute archive: daily bars, trading calendar,
  eligibility, survivorship hygiene, and a cross-sectional rank-portfolio engine bound to a
  written pre-registration (`docs/phase6-preregistration.md`).
- `discovery/`: momentum, volatility, volume, and trend screeners feeding the gateway.
- `api/` and `web/ui/`: FastAPI REST + WebSocket, React (Vite, TypeScript, Tailwind, Recharts).
- `alerts/`, `analytics/`: health monitoring, shared performance metrics.

Roughly 49k lines of Python and 3k of TypeScript, with 1,200+ tests. IBKR paper-trading path
validated live on 2026-08-04 (`docs/live-validation-2026-08-04.md`).

## Quick start

Requires Python 3.11+, Docker, and Node for the UI.

```bash
make dev            # venv + dev dependencies
make infra          # Redis on 6380, TimescaleDB on 5433
make run            # gateway with the mock adapter
make run-aggregator
make run-strategy
make run-api        # dashboard at http://localhost:8000
make test
```

Alpaca and IBKR credentials go in a local `.env` (`ALPACA_API_KEY`, `ALPACA_SECRET_KEY`);
per-machine overrides in `config/local.yaml`. Both are git-ignored. Historical data under
`data/` is untracked except for the two universe lists.

Historical replay:

```bash
python -m axtrade.fulltest download --start 2025-08-01 --end 2026-02-01 --symbols AAPL MSFT GOOGL
python -m axtrade.fulltest run      --start 2025-08-01 --end 2026-02-01 --symbols AAPL MSFT GOOGL --capital 100000
python -m axtrade.fulltest oos --is-start 2024-08-01 --is-end 2025-08-01 --oos-start 2025-08-01 --oos-end 2026-02-01 --symbols AAPL MSFT
```

## How the project was run

Design documents before code (`next-gen-trading-platform-design.md`, `docs/phase*.md`),
falsification built in (binding pre-registrations, a stopping rule that closed strategy
research when the last pre-registered test failed), and periodic whole-project audits whose
findings are tracked to closure. `docs/PROGRESS.md` is the backward-looking log.

## License

MIT. See `LICENSE`.

## Status and disclaimer

Personal research project. Paper trading only. Nothing here is investment advice, and the
strategies included are documented as not profitable after costs on the tested data.
