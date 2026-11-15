# Administrator-controlled live synthetic market

The live simulator supplies genuine liquidity to the existing exchange. Compliance
Administrators explicitly start bounded sessions; authenticated humans trade through
the unchanged trader APIs. PostgreSQL remains the financial authority. This is a
single-process academic workload, not a production exchange or an animated market.

The original `backend/simulator/market_simulator.py` and `scripts/run_simulation.py`
remain unchanged. That deterministic verification harness creates isolated fixtures,
checks known scenarios, and removes only its own data. Live sessions instead reuse
eight persistent, administratively provisioned bot accounts and preserve their orders,
executions, positions, and account balances after stop. Startup never provisions bots
and never resumes an interrupted live session.

## Shared runtime and financial flow

```text
Compliance Admin -> /admin/simulator/* -> LiveMarketSupervisor
                                              |
                                      typed agent actions
                                              |
Human -> POST /orders -----------------> existing Coordinator.admit()
                                              |
                                  PostgreSQL reserve + COMMIT
                                              |
                                  existing single-owner Engine
                                     |                    |
                               real book snapshot    immutable TradeEvent
                                     |                    |
                               CacheWorker          bounded Dispatcher
                                     |                    |
                                   Redis           SettlementWorker
                                                          |
                                             PostgreSQL atomic COMMIT
                                                   |            |
                                                GraphWorker  RegimeWorker
                                                   |            |
                                                 Neo4j       pgvector
```

Both humans and bots share the coordinator lock, matching engine, settlement worker,
collateral rules, fees, cancellation refunds, and self-trade prevention. Redis follows
actual admitted book changes; it is a derived cache, not a source of matching truth.
Graph and regime jobs are handed off only after financial commit. Regime features use
committed prices and actual book observations. No artificial executions or derived
records are manufactured by the simulator.

The supervisor owns one asynchronous scheduling task on the application's event loop.
It never constructs a coordinator, engine, book, dispatcher, or settlement worker.
Blocking SQL reads use threads; matching methods and admission stay on the owner loop.
The existing database advisory lease rejects a second owner. Run one Uvicorn worker.

## Accounts and decisions

`scripts/seed_live_bots.py` provides `load_bot_specs()`, `inspect_existing_bots()`,
`provision_missing_bots()` and an explicit CLI. The immutable allowlist is:

```text
sim-live-mm-01@tradegraph.test
sim-live-mm-02@tradegraph.test
sim-live-mm-03@tradegraph.test
sim-live-noise-01@tradegraph.test
sim-live-noise-02@tradegraph.test
sim-live-noise-03@tradegraph.test
sim-live-momentum-01@tradegraph.test
sim-live-reversion-01@tradegraph.test
```

Provisioning uses the existing trusted administrative connection, Equities desk and
STANDARD fee tier. It atomically creates missing user/trader/KYC/margin associations
under an advisory transaction lock. New passwords are high-entropy random inputs to
bcrypt, immediately discarded and never printed. Initial funding defaults to 10,000,000
minor units and is restricted to 1–100,000,000. Existing passwords, balances, positions,
and KYC records are never reset. Partial/conflicting identities fail the entire operation.
Dry run is read only; `--apply` is required to write. Ordinary demo identities are never
selected or modified. Administrative environment/connection imports occur only in the
CLI path, not when the application imports the allowlist.

Provisioning validates synthetic KYC and all associations. The runtime has no KYC SELECT
grant; startup verifies the exact email, synthetic name, TRADER role, desk, fee tier and
margin association using its existing grants. It also refuses unresolved bot orders.
HTTP clients cannot provide trader UUIDs or extend the allowlist. Bots do not obtain JWTs.

Market makers maintain passive bid/ask quotes with a bounded spread and cancel stale
quotes. They HOLD when the external book prevents a valid bounded passive spread. Noise
traders vary sides, quantities, passive/aggressive choices, cancellations and eligibility
intervals. Momentum uses recent settled price direction with an 80/20 directional bias.
Mean reversion compares settled prices with their recent average and holds in neutral
conditions. These are transparent rules, not trained models.

Observations contain immutable copies of up to 20 book levels and 20 recent committed
prices, actual tick/lot metadata, and a separate synthetic reference. The seeded local
integer process allows upward, downward and sideways movement, clamps references to
roughly 50–150% of each session anchor, and respects Redis's exact price range. An empty
market bootstraps its synthetic reference at 1000 ticks. That reference is never exposed
as a committed execution or used to fabricate analytics.

Every strategy budgets actual available cash and the current maximum fee rate. Both
sides reserve collateral under the existing financial contract. Bounds are four
outstanding orders per bot, five lots per order, 1,000,000 minor units notional per
order, and 100 lots of directional inventory including same-side pending quantity.
The supervisor independently enforces action ownership, price, instrument, lot, quantity,
notional and outstanding/exposure limits; the existing reservation procedure is the
final authority on funds. Default composition is three makers, three noise traders,
one momentum and one reversion trader. Smaller counts select an allowlist prefix,
retaining three makers assigned across the selected instruments.

## Session state and stopping

Initial state is STOPPED. Explicit start validates configuration, active instruments,
the running settlement worker, all eight provisioned identities, and unresolved state
before creating one task. Duplicate start, start while STOPPING and start from ERROR
return conflicts. Sessions do not restart themselves. Generation uses monotonic pacing
without catch-up bursts; HOLD and cancellation decisions also consume scheduling slots.
Consequently actual order attempts may be below the configured upper rate.

Queue pressure or retrying derived workers pause generation. Ten consecutive degraded
scheduling turns end the session in ERROR after attempted safe cleanup. Expected
reservation rejections are counted and use the existing bounded decision pacing; funds
are never replenished. Slow observations/account reads cannot cause a new action after
the deadline. An already-started financial operation can extend the stop duration.

Stop sets STOPPING and prevents new bot submissions. It shields the owned task from
HTTP disconnects, lets admission finish, drains settlement, reconciles exact run-owned
order IDs against active/archive rows, cancels only still-active owned orders through
`Coordinator.cancel()`, drains again and verifies no bot orders remain. Human orders,
committed history and derived observations are preserved. Auto-expiry and application
shutdown take this same path. Lifespan stops the supervisor before closing admissions,
then stops settlement and derived workers and releases the existing owner lease.

STOPPED means financial cleanup completed. ERROR means an operation or cleanup failed;
no automatic recovery is attempted. Derived delivery can still be retrying after a
financially successful stop: `derived_workers` exposes this explicitly. Its values are
worker state, not fresh connectivity probes; use `/health` for dependency probes.

## API and frontend contract

All three routes require the existing Compliance Admin JWT dependency. Traders receive
403; missing/invalid authentication receives 401. Every successful response is a typed
`SimulationStatus`. The actual schemas, including error envelopes, are in `/openapi.json`.

| Endpoint | Request | Successful result |
|---|---|---|
| `POST /admin/simulator/start` | `SimulationStart` JSON below | 200, RUNNING |
| `POST /admin/simulator/stop` | No body | 200, STOPPED or ERROR after cleanup; repeated stop is safe |
| `GET /admin/simulator/status` | No body | 200, current reconciled session status |

`SimulationStart` forbids extra fields and uses strict integers (booleans/string coercion
are rejected):

| Field | Type / bounds | Default |
|---|---|---|
| `instrument_ids` | List of 1–3 distinct active IDs, integers 1–2^31−1 | Required |
| `bot_count` | Integer 4–8 | 8 |
| `orders_per_second` | Integer 1–5, global scheduling/attempt upper rate | 2 |
| `volatility` | `low`, `medium`, `high` | `medium` |
| `seed` | Integer 0–2^63−1 | 20261115 |
| `max_duration_seconds` | Integer 30–600 | 300 |

Only eight bot identities are authorized. The brief's suggested upper limit of twelve
cannot be reached without new identities, so 9–12 are rejected rather than creating
extra accounts or reusing a trader as multiple bots.

Example start payload (replace the illustrative instrument ID with an active ID):

```json
{"instrument_ids":[1],"bot_count":8,"orders_per_second":2,"volatility":"medium","seed":20261115,"max_duration_seconds":300}
```

All fields of `SimulationStatus` are always present:

| Fields | Type and meaning |
|---|---|
| `run_id` | Nullable UUID string; unique per session |
| `state` | STOPPED, RUNNING, STOPPING or ERROR |
| `started_at`, `stopped_at`, `last_action_at` | Nullable timezone-aware timestamps; stopped_at records loop termination even in ERROR |
| `active_bots` | Count currently enabled for scheduling, zero outside RUNNING |
| `instrument_ids` | List of configured IDs, empty before first start |
| `config` | Nullable complete SimulationStart object |
| `orders_attempted`, `orders_accepted`, `orders_rejected` | Actual coordinator admission attempts/outcomes |
| `orders_cancelled` | Successful supervisor cancellations with nonzero remaining quantity; excludes automatic engine STP residual processing |
| `active_bot_orders` | Count of run-owned OPEN/PARTIAL PostgreSQL rows |
| `committed_executions` | Count of execution rows involving exact accepted run order IDs; bot/bot fills counted once |
| `backpressure_events` | Actual paused ticks or coordinator capacity rejections |
| `last_error` | Nullable sanitized failure code; never a raw SQL/driver exception |
| `derived_workers` | Worker-name map to `ready`, `retrying`, or `initializing` |

Execution metrics are queried at status/final cleanup, not on every decision tick.
Sequence gaps are never counted as executions. The run ledger is bounded by session
duration/rate and lives in memory. Poll status modestly (for example once per second):
the frozen schema lacks an execution-order-ID index, so counting may scan history.

Response examples and native proof observations appear in the acceptance section below.
Start responds with the same schema in RUNNING, initially zero counters; stop returns
the completed financial outcome; status after stop returns that retained session.
Before any start, run/config/timestamps are null, lists empty and counters zero.

Start conflicts return 409 (`SIMULATOR_NOT_STOPPED` or `UNRESOLVED_BOT_ORDERS`). Invalid
configurations/instruments return 422. Missing bot setup returns 503
`BOT_ACCOUNTS_NOT_PROVISIONED`; unavailable settlement/coordinator returns 503
`TRADING_UNAVAILABLE`. Status reconciliation failure returns 503
`SIMULATOR_RECONCILIATION_REQUIRED`. Database failures use the existing sanitized
application handler. Cleanup errors return a 200 response whose **state is ERROR**;
clients must inspect state and last_error, not just HTTP status. Error envelopes use:

```json
{"error":{"code":"SIMULATOR_NOT_STOPPED","message":"SIMULATOR_NOT_STOPPED"}}
```

Future frontend controls can select instruments, bot count, generation rate, volatility,
seed and duration; start/stop sessions; and show these exact status fields. Trader
screens continue using `/orders`, `/orders/{order_id}/cancel`, `/orders/me`, `/account/me`,
and `/market/{symbol}/book`, `/trades`, `/analytics`. They must honor cache 503/stale
responses and eventual derived delivery. A read-only instrument-discovery endpoint is
a future integration consideration; none was added to this backend extension.

## Operational runbook

1. Use the existing native installations and data directories. Start stopped services
   with their existing configuration; these commands do not reset databases:

   ```bash
   brew services start postgresql@17
   brew services start redis
   neo4j start
   pg_isready -h /tmp -p 5432
   redis-cli PING
   neo4j status
   ```

2. Preserve the ignored `.env`. Verify configured runtime PostgreSQL credentials,
   Redis URL, Neo4j credentials and JWT secret using the existing README runbook.
   Runtime must remain nonprivileged NOINHERIT, `SERVICE_WORKERS=1`. Administrative
   CLI connections use POSTGRES_ADMIN_HOST/USER and existing libpq authentication.
   Do not rerun schema bootstrap or seeds on an initialized database.

   ```bash
   .venv/bin/python scripts/verify_schema.py
   .venv/bin/python scripts/seed_live_bots.py --dry-run
   .venv/bin/python scripts/seed_live_bots.py --apply --initial-cash 10000000
   .venv/bin/python scripts/seed_live_bots.py --dry-run
   ```

3. Start the API with one worker, in its own terminal:

   ```bash
   .venv/bin/uvicorn backend.api.main:app --host 127.0.0.1 --port 8000 --workers 1
   curl --fail http://127.0.0.1:8000/health
   ```

4. Discover actual instrument IDs using the existing runtime read connection:

   ```bash
   .venv/bin/python - <<'PY'
   from backend.config import Settings
   from backend.stores.postgres import Database
   for row in Database(Settings.from_env()).query(
       'SELECT id,symbol,tick_size,lot_size FROM instrument WHERE is_active ORDER BY id'):
       print(row)
   PY
   ```

5. In a Python terminal from the repository root, log in through the existing API.
   Supply existing demo credentials at the prompt; no bot login is needed:

   ```python
   import getpass
   import httpx
   client = httpx.Client(base_url='http://127.0.0.1:8000', timeout=90)
   def login(email):
       r = client.post('/login', json={'email':email,'password':getpass.getpass(email + ' password: ')})
       r.raise_for_status()
       return {'Authorization':'Bearer ' + r.json()['access_token']}
   admin = login('admin@tradegraph.test')
   human = login('alice@tradegraph.test')
   iid = int(input('Active instrument ID: '))
   symbol = input('Its symbol: ').strip()
   r = client.post('/admin/simulator/start', headers=admin, json={
       'instrument_ids':[iid], 'bot_count':8, 'orders_per_second':2,
       'volatility':'medium', 'seed':20261115, 'max_duration_seconds':300})
   r.raise_for_status()
   print(r.json())
   ```

6. Inspect actual bot liquidity; when an ask is present, submit a normal crossing
   BUY limit using the instrument's lot size. The order may race another trader
   or quote replacement; only the subsequent execution API proves a fill:

   ```python
   r = client.get(f'/market/{symbol}/book', headers=human)
   r.raise_for_status()
   book = r.json()
   print(book)
   lot = int(input('Instrument lot size from metadata: '))
   ask = book['asks'][0]  # inspect a nonempty, nonstale book first
   r = client.post('/orders', headers=human, json={
       'instrument_id':iid, 'side':'BUY', 'price_ticks':ask['price_ticks'], 'quantity':lot})
   r.raise_for_status()
   print(r.json())
   print(client.get(f'/market/{symbol}/trades', headers=human).json())
   print(client.get('/account/me', headers=human).json())
   print(client.get('/orders/me', headers=human).json())
   print(client.get(f'/market/{symbol}/analytics', headers=human).json())
   print(client.get(f'/market/{symbol}/book', headers=human).json())
   print(client.get('/admin/surveillance/cycles', headers=admin).json())
   print(client.get('/admin/regimes/similar', headers=admin,
                    params={'instrument_id':iid,'current':'true'}).json())
   print(client.get('/admin/simulator/status', headers=admin).json())
   ```

   Refresh trades/account after settlement and derived views after their workers
   converge. A surveillance cycle is not guaranteed by stochastic trading.

7. Stop through the administrator API and inspect its financial state:

   ```python
   r = client.post('/admin/simulator/stop', headers=admin)
   r.raise_for_status()
   print(r.json())
   print(client.get('/admin/simulator/status', headers=admin).json())
   client.close()
   ```

   STOPPED should have zero active bot orders; human orders may remain. The trader
   can cancel their own remaining orders through the existing cancel endpoint.
   An expired client timeout does not revoke a committing admission or cancel the
   supervisor. Reconnect and read status rather than assuming cleanup succeeded.

8. For ERROR or refused startup, inspect under administrator control, read only:

   ```sql
   SELECT id,trader_id,instrument_id,side,quantity,filled_quantity,status
   FROM public."order" WHERE status IN ('OPEN','PARTIAL') ORDER BY id;
   SELECT id,buy_order_id,sell_order_id,price_ticks,quantity,executed_at
   FROM execution ORDER BY id DESC LIMIT 100;
   SELECT trader_id,cash_balance,escrow_balance FROM margin_account;
   ```

   Follow the existing [operator reconciliation procedure](backend-demo.md#operator-reconciliation-and-crash-boundary).
   Do not silently clear stuck orders, reset balances, invent missing fills or start
   a second matcher. ERROR cannot be reset through these endpoints. Restart only
   after reconciliation and a clean existing startup check; it creates STOPPED state.

## Acceptance report — 15 November 2026

### A. Repository baseline

Branch `main`; original HEAD `7e607cab6b8a622676ab6da3e026ee968061d815`;
initial working tree clean. Baseline native suite: 192 passed (47.25s). Final
implementation suite: 256 passed (56.12s), zero failures/skips. Final phase and ledger
commit identifiers are recorded in the [phase ledger](live-market-progress.md) and
local Git history; no remote push was performed.

### B. File-by-file implementation manifest

| File | Change / responsibility and principal interfaces | Reused components / placement |
|---|---|---|
| `scripts/seed_live_bots.py` | New BotSpec, load_bot_specs, inspect_existing_bots, provision_missing_bots, main | Existing administrative DB connection; operational CLI belongs in scripts |
| `backend/simulator/market_model.py` | New immutable MarketObservation, SyntheticMarketModel.next_reference_price | Pure integer market inputs/reference modeling in simulator |
| `backend/simulator/agents.py` | New action union, AccountState, ActiveOrder, TradingAgent and four strategies | Existing price/lot/collateral conventions; decisions only in simulator |
| `backend/simulator/live_supervisor.py` | New SimulationState/Config, build_agent, LiveMarketSupervisor start/stop/status/shutdown, observation, action, reconcile and cleanup helpers | Existing Coordinator, NewOrder, Database, settlement/derived workers; runtime orchestration in simulator |
| `backend/api/routes/simulator.py` | New strict SimulationStart, SimulationStatus, error models and three handlers | Existing admin dependency and application error conventions; additive HTTP module |
| `backend/api/main.py` | Minimal modification: shared supervisor construction, router registration, shutdown ordering | Existing lifespan and matching owner, no second trading pipeline |
| `tests/unit/test_live_agents.py` | New deterministic reference/strategy tests | Pure component tests in unit directory |
| `tests/unit/test_live_supervisor.py` | New lifecycle, race, pressure, validation, expiry and bounded-query boundary tests | Explicit boundary doubles, not claims of native financial proof |
| `tests/integration/test_live_provisioning.py` | New native provisioning/idempotency/conflict/funding/schema tests | Existing rolled-back DB fixture with explicit outer transaction |
| `tests/integration/test_live_simulator_api.py` | New RBAC, strict validation, contract, duplicate start, lifecycle tests | Existing API fixtures, actual persistent bot allowlist and existing instruments |
| `tests/integration/test_live_simulator.py` | New isolated native fixture, deterministic proof agent, human/bot and safety/outage tests | Actual API/coordinator/matching/settlement/Redis/Neo4j/regimes; test-only identity namespace |
| `docs/architecture/live-market-progress.md` | New phase audit/test/commit ledger | Existing architecture evidence directory |
| `docs/architecture/live-market-simulator.md` | New architecture, exact API, runbook and acceptance report | Existing backend contracts and reconciliation documentation |
| `README.md` | Short live-simulator documentation pointer | Existing README instructions preserved |

### C. Completed implementation phases

| Phase | Verification before phase commit | Local commit |
|---|---|---|
| 0 audit | 192 baseline native tests; 13 tables, zero active orders, three services healthy | Read only |
| 1 provisioning | 32 provisioning/database/RBAC tests; explicit dry-run and idempotent apply | fb55e1b; test-isolation follow-up 3a23a23 |
| 2 strategies | 128 unit tests | dae7a49 |
| 3 supervisor | 142 unit + 44 native financial/concurrency tests | 0f835b7 |
| 4 API/lifecycle | 14 native API/pipeline + 142 unit tests | 0041281 |
| 5 human/bot integration | 12 native proof/polyglot tests | fd60eee |
| 6 safety/regression | 256 full-suite tests + standalone deterministic CLI, native checks | a4a155b |
| 7 documentation | 45 strategy/supervisor + 3 native API tests; schema/runbook/link checks | 87d7568 |

Every phase has its required focused local commit. The phase 1 follow-up corrects a
test transaction boundary without rewriting history. The original audit's sandbox-only
test attempt could not reach local databases; rerunning with native access established
the genuine 192-test baseline. No failed/skipped native verification is hidden.

### D. Final backend architecture

The shared flow above is the implemented flow: administrator → supervisor → typed
agents → existing coordinator → committed reservation → existing matcher → settlement
queue/worker → committed execution → existing graph/regime consumers. Redis follows
actual book changes. Human orders join at the very same coordinator and lock.

### E. API contract evidence

The request and complete status fields above are the actual implemented schemas.
All endpoints and error models appear in OpenAPI and pass authenticated native tests.
Start/stop/status use the same response model; the measured stop response below also
describes a subsequent status response. Start has RUNNING/8 enabled bots and initially
zero counts, while stop retains its completed run metrics.

### F. Human–bot native proof

The exact final run observations and full stop response follow below. These are
isolated test identities, not demo users or persistent production bot IDs. A test-only
allowlist namespace substitution exercises the same identity-association checks and
an internal deterministic strategy seam; no financial operation or derived delivery
is mocked. Persistent allowlist startup/RBAC is independently tested by the API tests.
Execution history was verified after stop and after a clean restart, then only owned
fixture data was removed. No persistent/demo history was deleted.

| Observation | Actual value |
|---|---|
| Human identity | `live-proof-trader-ea91924077b8@tradegraph.test` / `74a428d0-ceca-4377-9395-123f616283de` |
| Bot identity | `live-proof-0-ea91924077b8@tradegraph.test` / `493cde87-d721-4b80-97a2-5f711b19407b` |
| Instrument | `LIVEea91924077b8`, ID 730, tick/lot 1/1 |
| Resting bot quote | SELL 100 × 2, order 5488 |
| Human crossing order | BUY 110 × 1, order 5490 |
| PostgreSQL execution | **88457**, price **100**, quantity **1**, `2026-11-15T23:02:30.568066+05:30` |
| Bot reservation | Cash 999799, escrow 201 from initial cash 1000000 |
| Bot after stop | Cash 1000099, escrow 0; net position −1, gross realized PnL 0 |
| Human after fill, own resting bid still reserved | Cash 999848, escrow 51; net position +1, gross realized PnL 0 |
| Human after cancelling their own bid | Cash 999899, escrow 0 |
| Fees | Maker 1, taker 1 minor unit; combined cash 1,999,998 after releasing reservations |
| Redis before human trade | Ask 100 × 2, version 1, nonstale |
| Redis after human trade | Bid 50 × 1 / ask 100 × 1, version 3, nonstale |
| Redis after simulator stop | Human bid 50 × 1, no asks, version 4, nonstale |
| Neo4j read-only verification | Trade count 1, notional 100 |
| Regime and analytical facts | Snapshot 1006; VWAP 100, band volume 1, one settled fill |
| Stop and restart | STOPPED, zero bot orders, one committed fill; human bid unchanged; cold restart STOPPED with settled analytics |
| Same-event replay | `False` (no additional financial effect) |

All IDs above were observed against real native stores. The isolated fixture's records
were removed only after preservation-through-stop/restart and external-counterparty
checks; these are evidence IDs, not promises that disposable test rows remain queryable.

Example start response excerpt (initialization shape for this recorded session; all
status fields described above are included by the endpoint):

```json
{
  "run_id": "f775ddda-0180-44eb-9247-c79037bffdc1",
  "started_at": "2026-11-15T17:32:30.504601Z",
  "config": {
    "instrument_ids": [
      730
    ],
    "bot_count": 8,
    "orders_per_second": 5,
    "volatility": "low",
    "seed": 20261115,
    "max_duration_seconds": 30
  },
  "state": "RUNNING",
  "active_bots": 8,
  "orders_attempted": 0,
  "orders_accepted": 0,
  "committed_executions": 0
}
```

Actual `POST /admin/simulator/stop` response from the proof:

```json
{
  "run_id": "f775ddda-0180-44eb-9247-c79037bffdc1",
  "state": "STOPPED",
  "started_at": "2026-11-15T17:32:30.504601Z",
  "stopped_at": "2026-11-15T17:32:30.669345Z",
  "active_bots": 0,
  "instrument_ids": [
    730
  ],
  "config": {
    "instrument_ids": [
      730
    ],
    "bot_count": 8,
    "orders_per_second": 5,
    "volatility": "low",
    "seed": 20261115,
    "max_duration_seconds": 30
  },
  "orders_attempted": 1,
  "orders_accepted": 1,
  "orders_rejected": 0,
  "orders_cancelled": 1,
  "backpressure_events": 0,
  "active_bot_orders": 0,
  "committed_executions": 1,
  "last_action_at": "2026-11-15T17:32:30.519302Z",
  "last_error": null,
  "derived_workers": {
    "redis": "ready",
    "neo4j": "ready",
    "regimes": "ready"
  }
}
```

`GET /admin/simulator/status` after that stop retains the same session. Response excerpt:

```json
{
  "run_id": "f775ddda-0180-44eb-9247-c79037bffdc1",
  "state": "STOPPED",
  "active_bots": 0,
  "orders_accepted": 1,
  "orders_cancelled": 1,
  "active_bot_orders": 0,
  "committed_executions": 1,
  "last_error": null,
  "derived_workers": {
    "redis": "ready",
    "neo4j": "ready",
    "regimes": "ready"
  }
}
```


### G. Regression evidence

Original 192 tests plus 64 new tests: **256 passed, 0 failed, 0 skipped**, one existing
Starlette/httpx deprecation warning, 56.12s. Unit suite: 157 passed. Native suite includes
SQL constraints/RBAC, ordered locking, replay, escrow, exact fees, positions, STP,
partial cancellation, human preservation, reservation/settlement stop races, actual
Redis/Neo4j outages/recovery, lifecycle conflicts and startup protection.

Separately, unchanged `scripts/run_simulation.py --seed 20261115` produced 18 executions,
race 3 accepted/5 rejected, same-event replay no-op, conflicting replay rejected,
rehydrated analytics, complete scoped cleanup and existing-data preservation. Native
schema verification passed: exactly 13 tables, zero unresolved active orders,
nonprivileged NOINHERIT runtime, Redis PING and Neo4j connectivity healthy. Compileall
and structural diff checks passed. Integration transport is in-process ASGI HTTP with
real native stores; no external-network latency/performance guarantee is claimed.

### H. Structural preservation

The original directory structure is retained, with no new top-level directory. Frontend,
schema/ER, financial SQL, matching engine, reservation/settlement/cancellation formulas,
stores/workers, JWT/RBAC, configuration, deterministic simulator, dependencies and all
original tests are unchanged. No additional infrastructure or matching owner was added.
Only the approved six-line FastAPI integration and short README pointer modify existing
files. All other work is in the manifest's new appropriately located files.

### I. Commit history

See the phase table and [full SHA ledger](live-market-progress.md). Required messages
are `Live sim phase 1: provision persistent synthetic traders`, `Live sim phase 2:
implement market model and trading agents`, `Live sim phase 3: implement live market
supervisor`, `Live sim phase 4: add admin simulator API and lifecycle integration`,
`Live sim phase 5: prove human and bot trading integration`, `Live sim phase 6: verify
safety and preserve backend regressions`, and `Live sim phase 7: document live simulator
and final acceptance`. Commits are local only; nothing was pushed.

### J. Remaining limitations

- Single matching owner and single API worker; finite queues and conservative admission
  capacity bounds can reject large books/backlogs.
- Process-local session ledger and nondurable event queue: no durable event journal,
  exactly-once delivery claim, automatic interrupted-session recovery or missing-trade
  replay. Existing unresolved-order startup refusal remains.
- Stop waits for real financial operations; it cannot safely provide a hard short timeout.
  Financial ERROR needs operator reconciliation. Derived retries can outlive a safe stop.
- Finite synthetic cash; no automatic top-up. Only eight approved bots, 4–8 enabled per
  session. Rule-based agents approximate market behavior; stochastic interactions depend
  on human activity and scheduling. Seeded decisions are reproducible for given inputs,
  not a guarantee of identical real-time executions or surveillance cycles.
- Historical position recomputation, startup analytics hydration, request-key/seen-ID
  retention and execution-count queries grow with history. Decision reads are bounded,
  but status counting may scan execution history under the unchanged schema.
- Native PostgreSQL/pgvector, Redis and Neo4j are required for full integration. This is
  neither production exchange performance nor a scalability/durability upgrade.

### K. Frontend readiness

A separately designed frontend can now implement admin configuration, start/stop/status,
actual counters, failure/retry displays, and shared market trading using the endpoints
above. It must display ERROR/STOPPING accurately and distinguish admitted orders from
committed executions. No frontend was designed or implemented in this work.
