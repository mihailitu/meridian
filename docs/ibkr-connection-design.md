# IBKR connection design

> Drafted 2026-07-19 while the mock live-validation shakedown ran. Scope:
> what it takes to go from "fake-verified" (phase-4 iteration 4) to a real
> TWS/IB Gateway connection for (a) market data incl. the A3 dynamic
> subscribe bridge, and (b) paper-account order execution (old audit C2).
> Live (real-money) trading stays out of scope — nothing has earned it
> (ROADMAP, retired list).

## What already exists

- `gateway/ibkr.py` — `IBKRAdapter` over ib_insync 0.9.86 (installed):
  connect, qualify+subscribe, dynamic `add_symbols`/`remove_symbols`,
  cumulative→delta day-volume handling, tick queue → `stream_ticks()`.
- `oms/broker.py` — `IBKRBroker`: market/limit orders, orderStatus +
  execDetails events → Fill callbacks, cancel, `get_positions`. Selected by
  `OrderManager` when `oms.paper_mode: false`.
- Both are exercised only against fakes (phase-4 e2e bridge test; unit
  suite). No process has ever connected to a real TWS.

## Connection topology (and the first blocker)

Gateway (data) and strategy-runner (orders) are **separate OS processes**,
so a live setup always has **two concurrent IB API connections**. IBKR
requires a unique `clientId` per connection — and today both sides read the
same `gateway.ibkr.client_id: 1`. The second process to connect is
rejected ("client id is already in use"). This is a guaranteed
first-minute failure.

**Decision D1**: split client IDs by role.
- `gateway.ibkr.client_id: 1` — market data (unchanged).
- `oms.ibkr_client_id: 2` (new key, default 2) — `OrderManager` builds the
  broker's `IBKRConfig` from `gateway.ibkr` with the client_id overridden.
Reserve 3+ for ad-hoc tools (smoke script uses 9x so it can run while
services are up).

## Market data type (the second blocker)

The adapter never calls `reqMarketDataType`, so it requests live streaming
data — which errors (code 354) unless the account has paid market-data
subscriptions. A fresh paper account has none.

**Decision D2**: new config `gateway.ibkr.market_data_type: delayed`
(`live` | `delayed`, mapped to reqMarketDataType 1 / 3, set once after
connect). Default **delayed**: 15-minute-late ticks are fine for plumbing
validation (bars build, indicators compute, orders route). Anything
strategy-real needs `live` + subscriptions (or data sharing from a funded
account's login) — that decision is deferred until a strategy earns it.
The delayed default also means ticker fields can be `delayedLast` etc.;
ib_insync maps them into `last`/`bid`/`ask` transparently, so the adapter
code is unchanged.

## Live-port safety guard

IBKR-paper vs IBKR-live is distinguished ONLY by port: TWS 7497 paper /
7496 live; IB Gateway 4002 paper / 4001 live. With `oms.paper_mode: false`
(required to select `IBKRBroker` at all), a config typo away from real
orders.

**Decision D3**: `IBKRBroker.connect()` refuses ports 7496/4001 unless a
new explicit `oms.ibkr_allow_live: true` is set (default false). The
refusal names the port and the flag. One `if`, removes the worst accident.

## Disconnect lifecycle

TWS auto-logs-off daily and IB Gateway restarts weekly; ib_insync fires
`disconnectedEvent`. Today `IBKRAdapter._connected` only flips on our own
`disconnect()` — after a TWS restart the tick loop would spin silently on
an empty queue. The phase-5 tick-staleness watchdog (300s) would flag it,
but recovery should be structural:

**Decision D4**: hook `disconnectedEvent` in both adapter and broker →
mark disconnected. For the adapter this ends `stream_ticks()`, which the
gateway's `LoopSupervisor` already treats as a dead stream → reconnect
with backoff (same path the Alpaca death detection uses, P2-10). For the
broker, `submit_order` already raises when not connected; add a
reconnect-on-next-submit attempt with the same guardrails. Full unattended
resilience (auto-relogin through TWS restart windows) is IBC/Gateway
territory — deferred to the unattended stage, not the validation day.

## Subscription limits (bridge sizing)

Default market-data line cap is ~100 concurrent. Discovery auto_subscribe
pushes high-score symbols on top of the 5 config names. Fine at today's
scale, but the bridge has no cap of its own.

**Decision D5**: cap total dynamic subscriptions in the adapter
(`gateway.ibkr.max_subscriptions: 90`; `add_symbols` logs and skips past
the cap). Contract qualification failures already log-and-skip.

## Runtime infrastructure

- **Validation stages (attended): TWS desktop, paper login, on the
  workstation.** The TWS UI doubles as an independent verifier for the
  order tests — seeing the order/fill in the TWS blotter confirms our DB
  against IBKR's own view, which no headless setup gives us.
  One-time TWS config: Global Configuration → API → Settings → enable
  "ActiveX and Socket Clients", port 7497, add 127.0.0.1 to trusted IPs,
  **uncheck** "Read-Only API" (else order submission is rejected).
- **Unattended stage (later): IB Gateway + IBC** (or the community
  dockerized ib-gateway) for auto-login and restart handling. Credentials
  via `.env`, same pattern as Alpaca. Not needed for any validation stage.
- **User-side prerequisite**: an IBKR account with paper trading enabled
  and TWS installed — nothing in the repo can do this part.

## Validation plan (staged, each with a hard gate)

- **S0 — smoke (10 min, any hour, market closed OK)**:
  `scripts/test_ibkr_connection.py` (new; mirrors
  `test_alpaca_connection.py`): connects data + order clientIds
  simultaneously, qualifies AAPL, requests one delayed snapshot, prints
  account summary (confirming it's the paper account, DU-prefix).
  Gate: both connections up at once; account id starts with "DU".
- **S1 — data path (market hours)**: `start-all.sh ibkr`, discovery
  auto_subscribe off. Same checks as the mock shakedown: ticks → 1m/5m
  bars → indicators → DB rows → dashboard. Gate: bar counts match wall
  clock for all 5 symbols; staleness watchdog quiet.
- **S2 — A3 live (market hours)**: auto_subscribe on. Gate: discovered
  symbols appear in `reqMktData` (adapter log), their ticks flow, and
  `remove_symbols`/re-subscribe churn stays under pacing warnings.
- **S3 — orders (old C2; market hours, paper account)**:
  `oms.paper_mode: false`, port 7497. Scripted, not strategy-driven:
  1-share MARKET buy → fill event → `fills`/`positions` rows match the TWS
  blotter; far-from-market LIMIT buy → cancel → terminal status, no fill;
  `get_positions()` reconciles with TWS. Gate: DB and TWS agree exactly.
- **S4 — strategy loop**: `discovery_momentum` end-to-end against the
  paper account for a session, attended. Gate: every order in the DB has a
  matching TWS record; risk limits (max_positions etc.) observed.
- **S5 — unattended** (after alert channels, C1): IB Gateway + IBC, a full
  day, no manual touch. Gate: zero unexplained alerts; clean daily-restart
  recovery.

## Implementation notes

D1–D5 are small, well-specified changes (config keys + a few guarded
lines each) plus the S0 smoke script — implementer-grade once this design
is agreed; the fake-IBKR unit tests extend naturally (clientId split and
port guard are pure-config assertions). Suggested order: D1, D2, D3
(needed for S0/S3), then D4/D5 (needed before S2 runs long).

## Python 3.14 / ib_insync status (verified 2026-07-19)

`import ib_insync` at module level fails under this venv's Python 3.14
(`eventkit` calls `get_event_loop()` at import time with no running loop).
Inside a running event loop it imports fine — verified empirically. The
runtime code already imports it inside `async def connect()` in both the
adapter and broker, so services are unaffected; the S0 smoke script also
defers its imports. **Constraint: never import ib_insync at module level**
anywhere in the codebase or scripts.

Forward item (not blocking): ib_insync is archived/unmaintained (author
passed away in 2024). The maintained fork is `ib_async` (ib-api-reloaded
org), a near drop-in replacement. Migrate when IBKR work goes beyond
validation — pin it as part of the S5/unattended hardening, not before.

## Implementation status

D1–D3 + the S0 smoke script + unit tests landed 2026-07-19 (1,209 unit
tests green). D4 (disconnectedEvent hook) and D5 (subscription cap) are
still open — needed before S2 runs long, not before S0/S1.

## Open questions for the user

1. Does an IBKR account with paper trading exist, and is TWS installed on
   this workstation? (S0 is blocked on this; everything else can land.)
2. Any paid market-data subscriptions on the account (changes D2's
   default from delayed to live for the data stages)?
3. Sequencing: land D1–D5 + S0 script now, or after the Alpaca live-paper
   validation day (Monday) concludes?
