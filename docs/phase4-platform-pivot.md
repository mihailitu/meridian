# Phase 4: Platform pivot

> Executes Option B from the phase-3 fork (see `docs/phase3-trustworthy-harness.md` and
> ROADMAP "What's next"). Decision date: 2026-07-03. The strategy-search phase is concluded:
> six strategies, honestly measured, all lose. The project's demonstrated value is the
> event-driven platform plus the calibrated, falsification-capable backtest harness — phase 4
> makes that the explicit deliverable and closes the gaps between "works in fulltest" and
> "live-paper capable".
>
> **Success criterion (reframed)**: a trustworthy strategy-evaluation platform with
> live paper-trading capability. NOT the v2.0 design-doc ambition (multi-market,
> millisecond latency, horizontal scaling, GPU ML) — those are retired, not deferred:
> millisecond latency is irrelevant at any horizon we can compete at, and there is no
> strategy to scale.
>
> **Execution model**: small iterations, each ending at a committable state with explicit
> evidence and a go/no-go gate, one commit (or small stack) per iteration on branch
> `phase4-platform-pivot`. Mechanical implementation is delegated to the `implementer`
> agent (sonnet) with a written spec; test/build runs go to `test-runner` (haiku); the
> session model reviews every diff against the spec and verifies each gate itself before
> the iteration commits. A gate failure is fixed inside its iteration — the next one never
> starts on top of an unexplained result.

## Iterations

| # | Iteration | Cost | Gate that ends it | Status |
|---|-----------|------|-------------------|--------|
| 1 | Reframe docs: ROADMAP + design-doc status | docs only | ROADMAP states the pivot + criterion | **DONE** (2026-07-03) |
| 2 | Green baseline + config hygiene | small code | full suite green; no strategy ships enabled | **DONE** (2026-07-03, 1002 passed; broker test was wrong, not the broker — raise-on-missing-price is the contract, manager translates to REJECTED) |
| 3 | Delete `ml/` end-to-end (audit B2) | medium code | suite green, UI builds, grep-clean | **DONE** (2026-07-03, 966 passed after removing 36 ML tests; migration 006 kept with ORPHANED note) |
| 4 | IBKR dynamic subscribe (audit A3) | medium code | bridge e2e test passes vs fake IBKR | **DONE** (2026-07-03, 976 passed; control loop verified to survive adapter raises; live-IBKR validation out of scope) |
| 5 | Paper integration test (audit C2) | code + ~min runs | deterministic e2e pass, bounded runtime | **DONE** (2026-07-03, 3× pass; caught + fixed F10 order-status clobber) |
| 6 | PaperBroker fill realism (audit C3) | medium code | buy_hold calibration unchanged; realism tested | **DONE** (2026-07-03, reject-over-cap semantics; calibration exact: $101,008.40 recomputed from parquet = reported, 1-month buy_hold) |
| 7 | Wrap-up: ROADMAP refresh, archive this doc | docs only | — | **DONE** (2026-07-03; doc kept in docs/ + linked from ROADMAP History, matching what phase 3 actually did rather than this row's original "archive" wording) |
| A* | *(optional, separate go/no-go)* point-in-time universe data | ~1–2 days + reruns | see below | not approved |

### Iteration 1 — Reframe docs

The direction change should be on record before code moves.

- ROADMAP: replace the Option A/B fork with the decision (B, 2026-07-03), the reframed
  success criterion, and this doc as the active plan. Keep the per-strategy DEAD table.
- `next-gen-trading-platform-design.md` header: change "several sections have drifted" to an
  explicit **retired-ambitions list** (multi-market, horizontal scaling, ms latency, ML layer,
  on_tick/on_regime_change hooks) pointing here. Do not rewrite the body — it's historical.
- Move the corresponding ROADMAP "Deferred" entries (multi-market, scaling, hooks) to a
  "Retired" section so nobody resurrects them by accident. External alert channels (C1) and
  PaperBroker realism (C3) stay live — C3 is iteration 6.

**Gate**: ROADMAP alone tells a newcomer where the project is and why. Docs-only; session
model writes this directly (judgment work, not delegated).

### Iteration 2 — Green baseline + config hygiene

Everything after this is verified by "full suite green", so the suite must actually be green:
4 failures pre-exist on main (3× `test_alerts.py` event-loop pattern, 1× `test_oms_broker.py`
— noted in phase 3 iteration 1 as tracked-not-ours; they're ours now).

- Fix the 4 pre-existing test failures. Investigate first; if any failure is a real product
  bug rather than a test-pattern issue, it gets its own mini-spec before fixing.
- `config/default.yaml`: ship **every** strategy `enabled: false` (momentum, mean_reversion,
  multi_timeframe, pairs currently ship `enabled: true` despite the phase-3 DEAD verdict).
  Comment each with its verdict + pointer to the ROADMAP table. Verify the strategy runner
  starts cleanly with zero enabled strategies (it should — confirm with a unit test, not vibes).

**Gate**: `make test` fully green, twice in a row (flake check); runner-with-zero-strategies
test exists and passes.

### Iteration 3 — Delete `ml/` (audit B2)

Scope is larger than the roadmap's "~2h": grep shows entanglement in `strategies/`
(`ml_prediction.py`, registry), `fulltest/` (orchestrator exclusion set, types, `__main__`
help text), `api/routes/ml.py`, frontend (`MLDashboard.tsx`, `useML.ts`, `types/ml.ts`,
plus wherever they're routed/imported), and `tests/unit/test_ml.py` +
`test_orchestrator_overrides.py`.

- Delete `ml/` package, `ml_prediction` strategy + registry entry, ML API route + its
  registration, frontend ML components/hooks/types + navigation references, `test_ml.py`,
  and ML references in fulltest code/help text and `config/default.yaml`.
- Leave `scripts/migrations/006_ml_models.sql` in place (applied-migration history is not
  rewritten); add a header comment marking the tables orphaned as of phase 4.
- CLAUDE.md: drop `ml/` from Key Modules and `ml_prediction` from the strategy list.

**Gate**: full suite green; `npm run build` succeeds; `grep -ri "ml_prediction\|axtrade.ml\b"`
over `src/ tests/ config/` returns only the migration comment and historical docs.

### Iteration 4 — IBKR dynamic subscribe (audit A3)

The discovery→trading bridge silently no-ops on the production broker: `gateway/base.py`
defines `add_symbols` as a do-nothing default and `IBKRAdapter` never overrides it.

- Base class: the default `add_symbols`/`remove_symbols` log a `WARNING` (silent drops become
  visible for any future adapter).
- `IBKRAdapter.add_symbols`: qualify + request market data for new contracts via `ib_insync`;
  `remove_symbols`: cancel market data. Idempotent (re-adding a subscribed symbol is a no-op).
- Tests against a fake `ib_insync` client (no live IBKR in CI): control-channel `subscribe`
  event → gateway → adapter → fake client sees the market-data request; same for removal.
  Follow the existing fake-adapter patterns in `tests/unit/test_gateway_control.py`.

**Gate**: bridge e2e test (pubsub in → fake IBKR call out) passes; suite green. Live-IBKR
validation is explicitly out of scope (no account wired up) — record that in the commit.

### Iteration 5 — Paper integration test (audit C2)

The fulltest harness proves the pipeline against historical replay; nothing proves the
*live-paper* path (mock adapter → aggregator → strategy runner → PaperBroker) end-to-end.

- In-process integration test bringing up gateway (mock adapter, 2–3 symbols), aggregator,
  strategy runner with `buy_hold` enabled, PaperBroker — on isolated Redis db (reuse
  `fulltest/isolation.py` patterns) and test DB. Assert: ticks flow, bars build, orders
  submit, fills land, positions match, clean shutdown drains (reuse the F7 drain logic).
- Runtime target ≤ ~2 min so it's runnable per-commit; mark with a pytest marker
  (e.g. `integration`) and add a `make test-integration` target. Deterministic: seed the
  mock adapter.

**Gate**: test passes 3× consecutively (determinism check); documented in CLAUDE.md test
commands.

**Found during execution (2026-07-03)** — the gate did its job on the first run:

- **F10 — OrderManager clobbered resolved order status.** PaperBroker fills synchronously
  inside `submit_order` (mutating the shared `Order` to FILLED; its fill callback persists
  the resolved row), then `OrderManager.submit_order` unconditionally stamped
  `order.status = SUBMITTED` and persisted again — so **every immediately-filled paper-mode
  order ended up permanently `status='submitted'` in the orders table** (fills/positions
  were correct, which is why fills-based fulltest analytics never noticed). Any consumer
  filtering `orders WHERE status='filled'` silently got nothing. Fixed inside this
  iteration: the SUBMITTED stamp now only applies while the order is still unresolved
  (PENDING/SUBMITTED), plus a regression unit test mimicking the synchronous-fill broker.
  Async brokers (IBKR) are unaffected — their fills arrive after the stamp.

Result: 3 consecutive passes (10.5s / 49.1s / 61.3s — duration varies with wall-clock
minute alignment), suite 980 passed, live state verified untouched (Redis db=0, `axtrade`
DB) with the test isolated to Redis db=2 / `axtrade_itest` / `it:`-prefixed streams.

### Iteration 6 — PaperBroker fill realism (audit C3)

Last known gap between paper fills and anything defensible: PaperBroker fills any size
instantly at close±slippage.

- Add a volume-participation cap (order quantity ≤ N% of the symbol's last bar volume,
  configurable; default off → behavior identical to today). Semantics per audit C3:
  **reject** over-cap orders (VolumeCapExceededError → OrderManager's existing
  rejection path), not partial fills — a partial fill's unfilled remainder would need new
  terminal-state machinery (the risk manager's open-order counter only decrements on full
  fill), and nothing on the platform needs that complexity yet. Revisit partial fills only
  if a live strategy earns it.
- Volume plumbing: strategy runner already pushes bar closes into the broker via
  `OrderManager.update_price`; extend it to carry bar volume. Unknown volume → no check
  (permissive, matches default-off posture).
- Unit tests for cap off (identical behavior), over-cap rejection (order REJECTED, counter
  decremented), under-cap fill, missing-volume passthrough, sell-side capping.
- **Calibration re-run**: 1-month buy_hold fulltest with realism OFF must still match the
  hand-computed value to the cent (regression guard on the phase-3 achievement).

**Gate**: calibration unchanged with feature off; partial-fill tests pass with it on.

### Iteration 7 — Wrap-up

ROADMAP refresh (platform state, what remains live: alert channels C1, anything discovered
during 2–6), archive this doc to `docs/iterations/archive/` per repo convention, fold any
operator-visible changes into CLAUDE.md.

### Iteration A (optional, not approved) — Point-in-time universe data

Only if explicitly wanted after 1–7: reconstruct point-in-time S&P membership from
Wikipedia's constituent-change history → `PointInTimeSymbolProvider` + survivorship-aware
download + pre-window daily seeding. This is a *platform data-quality feature* (makes the
harness falsification-capable for cross-sectional ideas); a 12-1 momentum trial may ride
along afterwards, with the ceiling stated up front: a pass replicates an ETF factor
exposure, it does not graduate a live bot. Gets its own mini-plan if approved.

### Explicitly not doing

- Any further signal-tweaking on current data at the current horizon (phase 3 answered it,
  six times).
- Multi-market, horizontal scaling, `on_tick`/`on_regime_change` hooks, any ML rebuild —
  retired with the design-doc ambition.
- External alert channels (C1) — real, but stays on ROADMAP until the platform core is done.
- Live (non-paper) IBKR trading — nothing has earned it.
