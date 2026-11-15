# TradeGraph frontend integration contract

This is the backend contract for a future role-separated Next.js application.
No frontend implementation is included. Existing trading, financial, authentication,
market and simulator contracts remain unchanged. The only new public route is the
authenticated active-instrument catalog.

## A — Architecture boundary

```text
Browser
   |
   v
Future Next.js application
   |
   v
Same-origin Next.js API proxy / Backend-for-Frontend (BFF)
   |
   v
Existing FastAPI application (one worker / one matching owner)
   |
   +--> PostgreSQL: authoritative financial and account records
   +--> Redis: derived top-20 depth
   +--> Neo4j: derived committed-counterparty relationships
   +--> Existing pgvector analytics within PostgreSQL
```

Humans and synthetic agents enter the existing coordinator/reservation/matching/
settlement pipeline. Instruments, users, order/account records and committed executions
come from PostgreSQL. Redis and Neo4j remain derived stores. No database connection or
arbitrary SQL capability should be exposed to the browser.

## B — Browser connectivity strategy

Use a same-origin Next.js BFF. The future server calls FastAPI using a private
server-side backend URL; it forwards the existing JWT in `Authorization: Bearer ...`.
Keep database credentials, backend secrets and signing keys out of browser code and
client-visible environment variables. Do not use persistent localStorage for passwords
or long-lived tokens.

Where practical, keep the browser session in a server-managed HttpOnly cookie, with
Secure in HTTPS deployments, appropriate SameSite/path/expiry settings, and CSRF
protection for mutations. The BFF must handle expiry and forward existing FastAPI
authorization errors. These are future frontend responsibilities, not new backend
session or token endpoints.

**No CORS modification is needed for this same-origin proxy strategy.** No CORS middleware
was added. A later direct-browser connection would require separate authorization for
an explicit restricted origin configuration; permissive global CORS is not recommended.
No Next.js proxy, cookies, UI, packages, build steps or WebSocket stream are implemented.

## C — Login and session contract

`POST /login` accepts strict JSON `{email: string, password: string}`. Email is 3–255
characters; password is 1–72 characters at the request layer. Extra fields are rejected.
Success is HTTP 200:

```json
{"access_token":"<JWT>","token_type":"bearer","role":"TRADER","expires_in":900}
```

The token placeholder and TTL above illustrate the contract, not credentials. Actual
`expires_in` comes from the configured JWT TTL (default 900 seconds, supported 60–3600).
Roles are exactly `TRADER` and `COMPLIANCE_ADMIN`. Use one login page and route users
to the appropriate future interface; FastAPI independently enforces permissions from
the token and current database identity. Administrator privilege does not grant
Trader-only account/order access.

Missing, malformed, expired or mismatched-identity JWTs return 401 `UNAUTHORIZED`.
Incorrect credentials return the same error. Wrong-role requests return 403 `FORBIDDEN`.
On expiry, clear the browser session and require login again. Logout clears the future
BFF/browser session; it does not revoke already-issued backend JWTs before their expiry.
There is no registration, password-reset, refresh-token or backend logout endpoint.

## D — Catalog and Trader route matrix

All endpoints below require a valid Bearer JWT. Catalog and market routes permit both
roles. Order/cancel/own-orders/account routes require a mapped TRADER identity.

### Active instrument catalog

`GET /instruments` → HTTP 200 `InstrumentCatalog`:

```json
{"items":[{"id":1,"symbol":"ACME","tick_size":1,"lot_size":1,"is_active":true},{"id":2,"symbol":"BETA","tick_size":5,"lot_size":10,"is_active":true},{"id":3,"symbol":"GAMMA","tick_size":10,"lot_size":5,"is_active":true}]}
```

This is the real native HTTP response observed for both roles. Values come from
PostgreSQL using the runtime read adapter, filtered `is_active=TRUE`, ordered by
`symbol,id`. An empty active set returns `{"items":[]}`; never invent a default.
Metadata fields are exactly integer `id`, string `symbol`, positive integer `tick_size`
and `lot_size`, boolean `is_active`. No price/company/sector/currency metadata is implied.
Use this catalog to map symbols in market paths to IDs in order/simulator requests.

### Trading and account endpoints

| Endpoint | Request / query | Success response and source |
|---|---|---|
| `POST /orders` | Strict `{instrument_id,side,price_ticks,quantity}`; optional `Idempotency-Key` header | 201 `{order_id,status:"OPEN",accepted_at}` after committed reservation and matching admission; this is not settlement acknowledgement |
| `POST /orders/{order_id}/cancel` | Owned order ID; no JSON body | 200 `{order_id,status:"CANCELLED",cancelled_quantity}`; waits for settlement before cancellation/refund |
| `GET /orders/me` | `limit` default 50, 1–100; `before_id` positive, default 2^63−1 | `{items:[OrderSummary],next_before_id}` from SQL active + archive |
| `GET /account/me` | No body | `{trader_id,cash_balance,escrow_balance,positions:[Position]}` from SQL |
| `GET /market/{symbol}/book` | Symbol | `{symbol,bids:[Level],asks:[Level],as_of,stale,version}` from Redis |
| `GET /market/{symbol}/trades` | `limit` default 50, 1–100; `before_id` positive, default 2^63−1 | `{items:[Trade],next_before_id}` from committed SQL executions, ID descending |
| `GET /market/{symbol}/analytics` | `lower_ticks` default 1; `upper_ticks` default 2^53−1, both ≥0 | `{vwap_ticks,window_fills,band_volume,as_of}` from existing settled in-memory analytics |

`NewOrder`: `instrument_id` is integer 1–2^31−1; `side` is BUY or SELL; price and quantity
are strict positive integers up to 2^63−1 at the request layer. Admission additionally
limits price to 2^53−1 for Redis exactness. Quantity must be a multiple of the selected
instrument's lot size. SQL enforces active metadata, overflow, collateral and fees.
Both BUY and SELL reserve cash in the existing synthetic collateral model.

`Idempotency-Key`, if supplied, is 1–128 characters from `[A-Za-z0-9._-]`. Duplicate
successful reservation keys for the same trader return 409 in this process. The cache
is process-local and bounded; this is not a durable cross-restart idempotency service.
A timeout/failure does not prove that a reservation or execution did not commit.
Reconcile `/orders/me`, `/account/me` and committed executions before deciding whether
to retry. Do not blindly resend with a new key or assume a reused key survives restart.
Order IDs are assigned by the backend, never chosen by the browser.

`OrderSummary` fields: `id`, UUID `trader_id`, `instrument_id`, `side`, `price_ticks`,
original `quantity`, `filled_quantity`, `status`, `created_at`, `updated_at`, and boolean
`archived`. Status is OPEN/PARTIAL/FILLED/CANCELLED. Compute arithmetic unfilled quantity
as `quantity-filled_quantity` using exact integers; a CANCELLED remainder is no longer
resting or reserved. Do not equate every SQL OPEN row with guaranteed executable depth
while asynchronous settlement is pending. A full page returns its last ID as cursor;
the following page may still be empty. A short/empty page has `next_before_id=null`.

`Position` fields: `instrument_id`, signed `net_quantity`, signed `realized_pnl`,
`pnl_basis:"gross"`. Cash is available cash; escrow is reserved collateral. Positions
can be negative for collateralized synthetic shorts. Gross realized PnL excludes fees;
cash incorporates actual assessed fees. No unrealized PnL, total account valuation,
deposits, withdrawals, real custody or total-exchange-liquidity contract exists.

`Level` contains integer `price_ticks` and aggregate `quantity`. Bids descend by price,
asks ascend; each side is limited to the top 20 levels. These are changing derived
quotes, not a promise of execution.

`Trade` fields: `id`, `instrument_id`, `buy_order_id`, `sell_order_id`, UUID
`buy_trader_id` and `sell_trader_id`, integer `price_ticks` and `quantity`, and
timezone-aware ISO timestamp `executed_at`. Only committed SQL executions appear here;
uncommitted match events must not be displayed as settled trades. Pagination uses
`id<before_id`. Empty history returns `items:[],next_before_id:null`.

Analytics use the existing 100-fill rolling VWAP and Fenwick executed-volume index.
`vwap_ticks` is a decimal string or null; `window_fills` is an integer capped at the
100-fill window, `band_volume` is integer executed quantity within the inclusive
price band, and `as_of` is the latest settled event time or null. No trades means null
VWAP/time and zero fills/volume. SQL timestamps may serialize with an explicit offset
instead of Z; treat all timestamps as ISO instants and format intentionally.

## E — Compliance Administrator route matrix

Every route in this table requires COMPLIANCE_ADMIN. Trader calls return 403.

| Endpoint | Request / query | Response |
|---|---|---|
| `POST /admin/simulator/start` | SimulationStart JSON in section F | SimulationStatus, HTTP 200 |
| `POST /admin/simulator/stop` | No body | SimulationStatus, HTTP 200 including possible ERROR |
| `GET /admin/simulator/status` | No body | SimulationStatus |
| `GET /admin/surveillance/cycles` | `limit` default 25, 1–100 | `{candidates:[{trader_ids:[UUID],edge_counts:[int]}]}` from committed-fact graph |
| `GET /admin/regimes/similar` | Required positive `instrument_id` ≤2^31−1; exactly one of `current=true` or repeated `features` query values; `k` default 10, 1–100 | `{matches:[{id,instrument_id,captured_at,features:[float × 6],cosine_distance:float}]}` |
| `GET /admin/disclosures/search` | Required `q` 1–500 chars; `limit` default 20, 1–100 | `{items:[{id,instrument_id:null-or-int,title,published_at,rank:float}]}` |
| `GET /admin/optimizer/compare` | `scenario`: price_band (default) or recent_executions; `instrument_id` positive default 1; lower/upper ticks positive defaults 1/2^53−1 | `{scenario,row_count,dataset_size,plans:{forced_sequential:object,automatic:object}}` |
| `GET /admin/desks/rollup` | None | `{items:[{desk_id,realized_pnl,execution_volume}]}` |

Regime features must be six finite values with a nonzero vector. `current=true` uses
the existing capture/upsert behavior; it is not a purely static read even though it
is an existing GET route. Do not prefetch or poll it automatically. No observation
returns 404 `NO_MARKET_OBSERVATIONS`; an empty similarity result returns `matches:[]`.
Cycle candidates are investigation leads, not findings of wrongdoing. Optimizer plans
perform real EXPLAIN ANALYZE reads and can be expensive. None of these endpoints is a
general-purpose SQL or database administration API.

## F — Simulator controls

Start body uses strict types, forbids extra fields and accepts no trader UUID:

| Setting | Bounds | Default |
|---|---|---|
| `instrument_ids` | 1–3 distinct active IDs, integers 1–2^31−1 | Required |
| `bot_count` | 4–8 | 8 |
| `orders_per_second` | 1–5 | 2 |
| `volatility` | low, medium, high | medium |
| `seed` | Integer 0–2^63−1 | 20261115 |
| `max_duration_seconds` | 30–600 | 300 |

The rate is a global upper bound on scheduling/order attempts, not guaranteed fills
per second. HOLD and cancellation decisions consume turns. Persistent identities and
strategies remain unchanged. Start validates instruments, bot associations and the
existing settlement worker. A successful RUNNING response admits a session; it does
not prove any trade is committed.

SimulationStatus always includes: nullable UUID-string `run_id`; `state`; nullable
`started_at`, `stopped_at`, `last_action_at`; integer `active_bots`; `instrument_ids`;
nullable complete `config`; integer `orders_attempted`, `orders_accepted`,
`orders_rejected`, `orders_cancelled`, `backpressure_events`, `active_bot_orders`,
`committed_executions`; nullable sanitized `last_error`; and `derived_workers` mapping
worker names to ready/retrying/initializing. Accepted orders and committed fills are
different metrics. Commit counts use actual execution rows involving exact run order
IDs; a bot/bot execution is counted once. Supervisor cancellation counts exclude
automatic engine self-trade residual processing. Enabled bot count is zero outside
RUNNING even while an in-flight action is finishing. See the existing
[live simulator contract](live-market-simulator.md) for full semantics.

| State | Frontend meaning |
|---|---|
| STOPPED | Initial idle state or verified financial cleanup completed |
| RUNNING | Synthetic decisions are enabled; neither every action nor a fill is guaranteed |
| STOPPING | No new decisions scheduled; admission/settlement/cancellation may still be completing |
| ERROR | Failure or failed cleanup requires operator attention; no automatic restart |

**HTTP 200 is not sufficient for a successful stop.** A verified response can be:

```json
{"state":"ERROR","last_error":"STOP_FAILED_RECONCILIATION_REQUIRED"}
```

This is an excerpt of the unchanged typed response. Show success only after state is
STOPPED; show STOPPING as pending and ERROR as a failure. Stop shields ongoing work
from caller disconnection rather than cancelling committing database threads. Refresh
status after timeouts. Derived jobs can still be retrying after safe financial cleanup;
read `derived_workers` and `/health` rather than claiming synchronized completion.
Duplicate start, start while STOPPING, and start from ERROR return 409. No UI Reset
button or automatic ERROR recovery is authorized.

## G — Market freshness and empty states

Redis `as_of` is the timestamp of the applied real book snapshot. The current adapter
marks depth stale if this stamp is absent or **older than 30 seconds**. It is not a
periodic heartbeat. A healthy but quiet exchange can have stale depth; stale=true
alone does not mean PostgreSQL or trading is down.

Missing cache metadata yields empty bids/asks, null as_of, stale=true, version 0.
An initialized empty book can instead have a timestamp, stale=false and version 0.
Neither contains fabricated levels. Label stale/delayed data explicitly; do not
promise a stale or empty snapshot contains live executable quotes.

`version` is the coordinator's book-change version within its process. It can restart
from zero after an accepted clean restart. The internal epoch is not exposed in the
current HTTP book model, so do not permanently reject lower versions as stale across
reconnect/restart; refresh the snapshot baseline and consider as_of. Redis updates,
settled SQL executions, in-memory settled analytics, Neo4j and regime observations
converge asynchronously and can briefly disagree without authorizing a fake fill.

Unavailable Redis returns 503 `CACHE_UNAVAILABLE`; an unknown symbol returns 404
`INSTRUMENT_NOT_FOUND`. Keep the last displayed cache snapshot clearly marked delayed
or unavailable; do not substitute invented prices. Missing history, null VWAP and no
regime observation are legitimate empty states. No schema or endpoint changes were
made to hide these distinctions.

## H — Initial polling policy

| Data | Recommended starting refresh |
|---|---|
| Depth | 1–2 seconds while trading view is active |
| Executions | 1–2 seconds while active |
| Own orders | 2 seconds while active; also after actions |
| Balances/positions | After actions and periodically during active trading |
| Simulator status | 2–3 seconds while controls/status are active |
| Surveillance | On demand |
| Regimes | On demand |
| Optimizer | Explicit user action only |

These are starting recommendations, not backend latency guarantees. Suspend polling
on inactive routes/tabs, avoid overlapping polls and use bounded backoff for failures.
Never poll expensive optimizer or graph/regime searches every second. No WebSockets
or frontend polling implementation is introduced in this sprint.

## I — Financial integers and JavaScript precision

Financial values remain integer JSON fields; no backend fields were changed to strings.
PostgreSQL BIGINT ranges beyond JavaScript's exact Number range of ±(2^53−1). A native
test verifies cash `9007199254741115` survives the current JSON response exactly in an
exact-integer consumer. Ordinary JavaScript JSON.parse/Number arithmetic can lose it.

Treat at least these fields as potentially unsafe for Number: order IDs and cursors,
execution IDs, buy/sell order IDs, quantities/filled/cancelled quantities, net positions,
cash and escrow, realized PnL, price_ticks, aggregate book quantities/band_volume,
desk execution_volume/PnL, disclosure/regime IDs and seed. Aggregated counts/versions
can also grow. Instrument/desk IDs are PostgreSQL INTEGER, but should still be validated.

The future BFF must forward financial response bodies losslessly (for example raw-body
pass-through) or use a deliberately designed lossless JSON parser/serializer. The
browser must also decode integer tokens exactly to BigInt or exact decimal strings
before formatting/arithmetic. Converting an already-rounded Number to BigInt cannot
repair lost digits. Native JSON.stringify cannot serialize BigInt directly; an explicit
lossless serializer is required for outgoing requests. Select a concrete library and
client representation in the frontend sprint rather than silently changing this API.

`price_minor_per_unit = price_ticks × tick_size`; `notional_minor = price_ticks ×
tick_size × quantity`, all exact integers. Validate `quantity % lot_size == 0`. Apply
currency formatting with exact integer/decimal operations; metadata does not include
a display currency or decimal scale to invent. VWAP is already a decimal string and
should use exact decimal formatting. Similarity vectors, cosine distance, disclosure
rank and optimizer timing metrics are floating-point analytical values, not money.

## J — Errors and retry decisions

The common envelope is `{"error":{"code":"...","message":"..."}}`; driver internals
and credentials are not public errors.

| HTTP/result | Existing codes / interpretation |
|---|---|
| 401 | UNAUTHORIZED: missing/invalid/expired identity or bad login; clear expired session |
| 403 | FORBIDDEN: wrong role; admin is not a trader |
| 404 | ORDER_NOT_FOUND (including non-owned), ACCOUNT_NOT_FOUND, INSTRUMENT_NOT_FOUND, NO_MARKET_OBSERVATIONS |
| 409 | INSUFFICIENT_FUNDS, DUPLICATE_REQUEST, ORDER_TERMINAL, EVENT_CONFLICT, SIMULATOR_NOT_STOPPED, UNRESOLVED_BOT_ORDERS |
| 422 | INVALID_REQUEST, INVALID_ORDER, INVALID_SIMULATION_CONFIG, CHOOSE_FEATURES_OR_CURRENT, INVALID_VECTOR |
| 503 | TRADING_UNAVAILABLE, DATABASE_UNAVAILABLE, CACHE_UNAVAILABLE, GRAPH_UNAVAILABLE, REGIMES_UNAVAILABLE, BOT_ACCOUNTS_NOT_PROVISIONED, SIMULATOR_RECONCILIATION_REQUIRED |
| HTTP 200 + simulator ERROR | Failure, not successful cleanup; inspect last_error and involve operator |
| stale=true | Delayed/absent cache timestamp, not proof of a dead financial backend |

Invalid price/quantity types or nonpositive values fail strict request validation;
bad lots/inactive instruments/overflow fail existing financial validation. Cancelling
a filled order returns 409 ORDER_TERMINAL; repeated cancellation of an already-cancelled
owned order can return zero quantity. Business conflicts need reconciliation, not
indiscriminate retries. A disconnected/timed-out POST may have committed; a new key
can create a second order. Retry transport only after reconciling persisted facts.

## K — Safe human/bot demonstration and readiness command

1. Verify the existing native PostgreSQL, Redis and Neo4j installations with the
   [README native runbook](../../README.md#getting-started). Preserve data directories
   and secrets. Do not bootstrap/reset an initialized database.
2. Verify identities: `.venv/bin/python scripts/seed_live_bots.py --dry-run`.
   If genuinely missing and deliberately authorized, provisioning is the explicit
   operator command below; the checker never invokes it or re-funds existing bots:

   ```bash
   .venv/bin/python scripts/seed_live_bots.py --apply --initial-cash 10000000
   ```

3. Start exactly one API process (after checking no matching owner is active):

   ```bash
   .venv/bin/uvicorn backend.api.main:app --host 127.0.0.1 --port 8000 --workers 1
   ```

4. With that server available, run:

   ```bash
   .venv/bin/python scripts/verify_frontend_readiness.py --api-base-url http://127.0.0.1:8000
   .venv/bin/python scripts/verify_frontend_readiness.py --api-base-url http://127.0.0.1:8000 --json
   ```

5. Authenticate Admin using POST /login; GET /instruments with that token and select
   an actual active ID/symbol/tick/lot combination.
6. POST /admin/simulator/start with valid bounds; confirm RUNNING, not a settled fill.
7. Authenticate Trader separately through POST /login; use that role's token for trading.
8. GET the selected symbol's book; inspect timestamp/staleness and actual bid/ask levels.
9. Submit a positive lot-aligned crossing BUY at a current ask, or SELL at a current bid,
   through POST /orders with a deliberate request key.
10. Wait for the actual execution to appear in GET /market/{symbol}/trades. A quote
    may be consumed/cancelled between observation and submission; no fill is guaranteed.
11. Refresh /account/me and /orders/me to distinguish reservations, fills and positions.
12. Inspect changed Redis depth, settled analytics, and on-demand administrator views.
13. Stop via POST /admin/simulator/stop; inspect state and last_error. Only STOPPED
    means financial cleanup completed; status can show STOPPING while it waits.
14. Confirm active_bot_orders=0 and that eligible bot residual quotes were cancelled.
15. Confirm human orders and committed history remain. A human must cancel their own
    eligible resting orders through the normal API when desired.

### Checker scope and output

The checker validates Settings/one worker; runtime PostgreSQL reads; the expected
13-table set, 18 FKs and vector/pgcrypto; active positive instrument metadata; all
eight bot associations via existing administrative read helpers; Redis PING; Neo4j
connectivity; HTTP /health and /openapi.json; and typed authenticated catalog/simulator
registration. The full existing schema verifier and tests separately validate deeper
constraints, grants and accounting. Authenticated route behavior belongs to integration
tests; the checker does not bypass JWT, obtain tokens or invoke simulator controls.

SQL transactions are forced read only. It issues SELECTs including a session-local
statement timeout, performs no migrations/provisioning/cancellations, alters no cache
or graph data, and never constructs an application/coordinator. `--timeout` defaults
to 3 seconds, allowed 0.1–10, for HTTP/Redis/Neo4j and SQL statements; PostgreSQL connect
timeouts retain the existing bounded runtime/admin configuration (admin helper: 10s).
Probe times add up; this is not a hard total-duration or latency guarantee.

Exit 0 means all essential checks passed; exit 1 means not ready. Warnings remain
separate from failures. Active orders can be valid in a running healthy exchange and
generate a cold-restart warning; they are not automatically cancelled or classified
as corruption. A missing/unhealthy API is an essential demonstration-readiness failure.
`trading_ready` is distinct from derived health: PostgreSQL can be available while
Redis/Neo4j is down. The checker requires all essential services and overall API health,
not just financial readiness. It prints sanitized actions, not credentials or raw
configuration/exception values.

Measured readiness report and verification evidence are appended below.

## L — Restart and operator boundary

The live session and event queue are process-local; the queue is not crash durable.
No automatic live-session restart, interrupted-trade recovery or missing-event replay
is implemented. Existing startup refuses unresolved OPEN/PARTIAL orders. Cold restart
is therefore not an ordinary way to clear a book. While the server is healthy, humans
can cancel their own eligible resting orders through the normal API before planned
shutdown. Bot stop does not cancel human orders. Failed financial state needs the
existing [operator reconciliation procedure](backend-demo.md#operator-reconciliation-and-crash-boundary).

Do not expose Reset Database, auto-cancel all users' orders, change balances, delete
history or invent trades to recover. A future frontend should explain the blocked
state and hand off to an operator, not automate destructive recovery.

## M — Known limitations

One matching owner and one API worker; no horizontal scaling. No WebSocket stream;
frontend updates initially poll. Redis can be stale or unavailable, and projections
are eventually consistent. No automatic crash recovery or durable journal. Trading
is synthetic/collateralized, without real-money transactions or security custody.
Agents are rule-based, not trained trading AI. Stochastic liquidity and surveillance
cycles are not guaranteed. Simulator stop preserves human orders. Historical position
recomputation and status counting grow with history; optimizer/graph work is not a
high-frequency UI operation. This contract does not claim production-exchange load,
latency, delivery or durability guarantees.

## Sprint verification and acceptance

### Baseline and outcome

**YES — the backend is ready for building the Next.js Trader and Compliance
Administrator interfaces using the contracts above.** All essential verification
checks passed on 16 November 2026. This is frontend integration readiness, not a
production-exchange or crash-durability certification. The verification server was
stopped cleanly afterward; an operator must run one API server for an actual demo.

Original HEAD: `795148b78de240acbd84bc78f101e6c774c2b0d5`, branch `main`, initially
clean. No existing instrument catalog or CORS middleware was present. Preflight:
13 tables, 3 active instruments, 8 valid bots, zero unresolved orders, no competing
matching owner, and PostgreSQL/Redis/Neo4j reachable. Baseline suite: **256 passed**,
one existing warning, 54.75s. Final suite: **284 passed, 0 failed, 0 skipped**,
63.12s. New coverage: **28 tests** (2 catalog, 7 frontend contracts, 19 checker cases).
Categories: 176 unit, 72 integration, 33 concurrency, 3 benchmarks. Original tests
are unchanged. The only warning is the existing Starlette/httpx deprecation.

### File-by-file implementation manifest

| Path | Change and principal interfaces | Reuse and placement |
|---|---|---|
| `backend/api/routes/instruments.py` | New InstrumentInfo/InstrumentCatalog and list_instruments; CATALOG_SQL | Existing actor, runtime Database.query and asyncio.to_thread; authenticated reads belong in API routes |
| `backend/api/main.py` | Minimal import and include_router only | Existing create_app/lifespan, coordinator and workers unchanged |
| `tests/integration/test_instrument_catalog.py` | New scoped catalog fixture, actual SQL/role/order/metadata/empty/read-only/OpenAPI tests | Existing accounts/login/wait utilities; native HTTP/SQL behavior belongs in integration tests |
| `tests/integration/test_frontend_api_contracts.py` | New QuietAgent seam and login, lifecycle, error, depth, settled pagination, account/order and BIGINT tests | Existing native fixtures, real reservation/settlement/stores, controlled failure gates; no financial stubs |
| `scripts/verify_frontend_readiness.py` | New run_checks/main, PostgreSQL/bot/Redis/Neo4j/HTTP probes, typed-route checks | Settings, Database, EXPECTED_TABLES, db_connect, load_bot_specs, inspect_existing_bots; operational CLI belongs in scripts |
| `tests/unit/test_frontend_readiness.py` | New classification, exit-code, warning, secret-redaction, malformed registration, read-only and no-start/no-write boundary tests | Controlled mocks for failures; native checker validated separately |
| `docs/architecture/frontend-integration-contract.md` | New sections A–M, runbook, measured acceptance evidence and phase records | Existing contracts and live simulator/operator documentation; no historical log overwritten |
| `README.md` | Short contract/checker pointer and read-only command | Existing installation and verification instructions preserved |

### Phase evidence and local commits

| Phase | Verified changes / tests | Commit SHA | Status |
|---|---|---|---|
| 0 | Read-only audit, native preflight, 256-test baseline | No commit required | Complete |
| 1 | Runtime authenticated catalog; 24 native catalog/order/market checks | `50f23661adfa28cef8a4060ad7a8129fdbfec97c` | Complete |
| 2 | Existing API contracts; 16 native new/old simulator checks | `a129dff5f4824e9659b85df7d83cc836239cabed` | Complete |
| 3 | Read-only checker; 176 unit + 9 native API checks, real-server readiness and SQL fingerprints | `e39f3eb5c23b53d8e218ab1484be00a186728a25` | Complete |
| 4 | This contract/README; final 284 tests, standalone simulator, native schema/bot/readiness checks | Recorded in the final agent report and local Git history | Complete |

Required messages are respectively `Pre-frontend phase 1: add authenticated instrument
catalog`, `Pre-frontend phase 2: verify authentication and market API contracts`,
`Pre-frontend phase 3: add read-only integration readiness checker`, and `Pre-frontend
phase 4: finalize integration contract and acceptance`. Commits are local only;
nothing is pushed. The phase 4/final HEAD SHA is reported after its creation without
amending earlier commits or embedding a circular self-reference in this document.

During phase 3 verification, two commands were mistakenly overlapped: an API regression
process and the native checker server. Matching-owner protection rejected competing
clients (two test failures) and fixture activity invalidated that fingerprint comparison.
Both were rerun sequentially: 9 API tests passed and all 13 table fingerprints matched.
No backend behavior or test assertion was weakened to correct this orchestration error.

### Authentication and simulator compatibility

Actual login responses for both roles were tested, including token type/role/TTL,
wrong credentials, missing/invalid/expired tokens, Trader denial on all simulator
controls, and Admin denial on Trader order/account routes. Both roles returned the
same authenticated real catalog shown above. Simulator start/stop/status request and
response models, bounds and source files are byte-for-byte unchanged. Real supervisor
states RUNNING/STOPPING/STOPPED and HTTP-200-with-ERROR were verified without inventing
statistics; unavailable settlement returned the existing 503. All old human/bot,
financial, derived-store outage/retry and shutdown-race integrations still pass.

### Actual operational readiness report

Executed the new CLI against a single running native FastAPI server using real HTTP,
then shut that verification server down before any further matching-owner tests.
Exit status **0**, no remaining checker warnings or failed essential checks:

```json
{
  "ready_for_frontend": true,
  "postgres": "up",
  "schema": "valid",
  "redis": "up",
  "neo4j": "up",
  "api": "up",
  "instrument_catalog": "registered",
  "active_instruments": 3,
  "bot_accounts_valid": 8,
  "simulator_api": "registered",
  "service_workers": 1,
  "active_orders": 0,
  "trading_ready": true,
  "overall_health": "ok",
  "derived_services": {
    "redis": "up",
    "neo4j": "up",
    "regimes": "up"
  },
  "warnings": [],
  "failures": []
}
```

Before/after hashes of **all 13 PostgreSQL tables** matched across the isolated checker
run, including account and financial data. The checker never started a simulator or
owned a matcher. API /health showed PostgreSQL/Redis/Neo4j/regimes up; actual authenticated
catalog responses for Trader/Admin matched. The existing bot CLI dry-run validated all
eight identities without writes. Missing bot/config/API/service cases, warning-only
active orders, exit status 1 and secret redaction were verified by controlled tests.

### Regression and preservation evidence

The unchanged deterministic CLI ran separately with seed 20261116: **18
executions**, race 3 accepted / 5 rejected,
same-event replay `no-op`, conflicting replay `rejected`,
scoped cleanup `complete`, existing data preserved `True`,
and analytics rehydrated after clean restart.

The original native schema verifier passed (13 tables/18 FKs, existing indexes,
forced RLS, privileges and demo associations). Structural diff confirms the original
directory layout and all financial SQL, matching, risk/clearing, workers/stores/events,
auth/JWT, configuration, deterministic/live supervisors and strategy files are unchanged.
No frontend file, dependency, secret or infrastructure changed. No new top-level folder,
WebSocket, database, broker, CORS policy or duplicate matching pipeline was introduced.
All implementation additions are in the manifest; existing-source modification is
limited to router import/registration plus the README pointer. No remaining essential
readiness blocker was found.

Verification artifacts for this run are under `/tmp/tradegraph-prefrontend/` (full/JUnit
results, readiness JSON, actual catalog response, schema and bot logs, deterministic
report). These are local operational artifacts, not secrets or committed database dumps.
