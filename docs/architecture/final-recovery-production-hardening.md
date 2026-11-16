# Final recovery and production hardening

Base: `9c4c64ded6f7129460eca8ff0e810dc60be09e84`.
Branch: `codex/final-recovery-production-hardening`.
Only durable recovery and production transport/stability are in scope.

## Phase 1: failure windows

Audit covers dispatcher, settlement worker, reservation coordinator, pure matcher/book,
TradeEvent, all derived workers/stores, startup, reservation/settlement/cancel SQL,
and restart diagnostics. PostgreSQL is the financial authority.

| Crash boundary | Committed SQL | RAM lost | Replay / risk / startup |
|---|---|---|---|
| Reservation begins, before COMMIT | None; transaction rolls back | Request | Retry via request key; no financial effect |
| Reservation COMMIT, before matcher | Order, escrow, optional request identity | Admission progress | Ambiguous: indistinguishable from resting order; startup refuses active orders |
| Matcher changes book, before events | Reservations only | FIFO removals, fills, STP decision | Unsafe to reconstruct pending matching from SQL; no committed execution identity |
| Events generated, before queue | Reservations only | Exact IDs, time, ordered fills | Unsafe; execution sequence gaps do not describe a fill |
| Settlement queue / transaction before COMMIT | Reservations; earlier fills may be committed | Remaining events | Rollback applies no financial effect; partial batch cannot be reconstructed exactly |
| Financial COMMIT before analytics | Execution, positions, balances, fill counts | Analytics / event progress | Exact TradeEvent reconstructable: canonical ID and greatest(order IDs) taker; settlement replay exact-match idempotent |
| Analytics before consumer handoff | Same canonical SQL | Queued derived work | Analytics replay safe by canonical ID; graph absolute aggregate rebuild safe; historical book observations absent |
| Redis / Neo4j / pgvector | Same; possibly regime snapshot | In-flight delivery and observation | Redis rebuild only from verified book; graph absolute aggregate replay safe; missing historical regime input cannot be invented |
| WebSocket send | Same | Connection queues | Best effort; reconnect requires authoritative HTTP snapshot; never financial replay |

`execution` contains every TradeEvent field except taker, which settlement enforces
as `greatest(buy_order_id,sell_order_id)`. It does not contain contemporaneous depth
or capture-time regime inputs. Regime snapshots already committed remain available;
missing historical observations are inherently non-reconstructable with current data.

A second owner is excluded by the session advisory lock. After owner death an
active-order check refuses startup; no orders are canceled. Historical execution
replay is bounded and idempotent. Startup must not be relaxed based on timestamps:
they describe reservation, not completed matching, and SQL fill counts lag RAM.

Phase 1 tests: `tests/concurrency/test_recovery_windows.py`, plus existing settlement
recovery tests. Test environment is newly created `tradegraph_test_final_hardening`
on dedicated PostgreSQL/Redis ports, never the configured financial database.
Phase status and exact verification/commit evidence follow below.

Phase 1 verification: **16 passed** (new crash-window suite and existing settlement
recovery suite, real isolated PostgreSQL, 6.53 seconds). Branch creation and initial
push confirmed by origin. No running financial process was killed. No financial
routine or matching rule was modified. Commit recorded in the next phase entry.

## Phase 2: durable publication intent

Phase 1 commit `60dd9d8` pushed and confirmed on origin.
New migration installs an AFTER INSERT trigger on execution, two uniquely keyed
consumer intents per canonical execution, per-consumer progress, bounded retry
metadata, pending index, and atomic historical backfill. Rollbacks remove both
execution and intent. No settlement SQL or fee arithmetic changes.

New `durable_outbox.py` claims one row with SKIP LOCKED and a consumer advisory
transaction lock, performs derived work only, and acknowledges after success.
External success followed by SQL rollback is deliberately at-least-once replay.
It never invokes settlement. Polling and backoff are bounded; missing historical
regime payloads remain visibly pending, never synthesized or acknowledged.
`outbox_worker.py` awaits in-flight writers before releasing ownership on shutdown.
Migration is explicit through `scripts/migrate_recovery.py`; only the selected
runtime identity receives progress grants. Trader and generic compliance roles
receive no outbox access. `verify_schema.py` recognizes the additive table.

Phase 2 verification: **32 passed**, durable outbox + settlement recovery + settlement
lock/fee invariants (15.43 seconds). Initial test run exposed a test deployment grant
mistake (legacy runtime name versus isolated `tradegraph_financial`); corrected the
isolated migration grant and reran all checks. No test result was suppressed.

## Phase 3: derived replay

Phase 2 commit `a8449a1` pushed and confirmed on origin.
Startup installs durable graph/regime consumers instead of volatile callbacks.
Settlement still uses the exact existing SQL routine; its connection now persists
regime features, capture/observation time and original depth/epoch/version before
COMMIT. Feature mathematics and VECTOR(6) similarity are unchanged. No current book
is used to invent a historical observation during replay. A metadata failure rolls
back the financial transaction and preserves fail-closed handling.

Graph replay uses existing absolute PostgreSQL pair aggregates. Startup rebuild and
outbox application share a projection writer advisory lock, preventing stale writes
from concurrent read-before-write. Regime upsert retains its existing unique minute
key, and delayed retries cannot overwrite an already delivered newer observation.
Legacy SQL-only executions retain missing-observation diagnostics; exact historic
regime recovery for those is **blocked**, since their depth was never persisted.

Redis retains owner epochs and monotonic per-epoch version checks. Startup still
rebuilds only a verified empty active book; active-order recovery remains blocked.
Cache notifications occur only after successful atomic Redis application. WebSocket
notifications stay best effort; browser reconnect uses existing HTTP snapshots.
No durable notification acknowledgment waits on a browser.

Files: `backend/api/main.py`, `backend/stores/postgres.py`,
`backend/stores/regimes.py`, `backend/workers/graph_worker.py`, dispatcher docstring,
`tests/integration/test_outbox_recovery.py`, isolated-stack migration wiring.
Verification: **40 passed** (outbox recovery, full order pipeline, polyglot consumers,
and concurrent outbox tests; 33.64 seconds). Frontend production build passed;
its incidental generated next-env change was discarded to preserve scope.
Additional phase 3 verification: **6 passed** including delayed regime retry ordering
(3.78 seconds). No skipped observations were treated as delivered.

## Phase 4: active-order restart safety gate

Phase 3 commit `12f55c3` pushed and confirmed on origin.
**Automatic active-order recovery is blocked; the existing refusal is preserved.**
SQL reconstructs order IDs, instruments, traders, side, limit, original/remaining
quantities, committed partial fills and reservations. IDs encode the accepted FIFO
sequence. It does not persist the completed admission turn, ordered pending fill
intents (IDs/times), STP residual action, or the precise resting/matching checkpoint.
Outbox intent starts at financial COMMIT and cannot repair pre-settlement intent loss.

Enabling restart safely requires a durable admission/match-intent protocol covering
reservation, matching turn, all fills and cancel/STP progress, plus a versioned book
checkpoint and owner fencing. That changes the admission/settlement protocol beyond
this narrow committed-event hardening. Reloading OPEN rows alone is not proof of
matching equivalence. No automatic cancellation, balance adjustment, FIFO change or
rematching workaround was added.

New tests cover BUY/SELL refusal with unchanged escrow, partial fill refusal and
exact duplicate replay, terminal archival restart and exclusion of a second owner.
Existing phase 1 tests cover reservation COMMIT and lost matching-queue boundaries;
existing matching/FIFO suites remain the regression authority.
Phase 4 verification: **40 passed** (active-order refusal, terminal restart, failure
windows, order book and engine invariants; 3.74 seconds). This phase is a verified
safety refusal, not a claim that active-order recovery is fixed.

## Phase 5: reconciliation diagnostics and readiness

Phase 4 commit `293b35d` pushed and confirmed on origin.
`reconcile_restart.py` remains read-only by default and exposes no repair command.
It checks current and archived order volumes, duplicate IDs across the archive,
execution/order references, exact outstanding escrow, net positions, owner locks,
durable consumer backlog/retries/missing observations, trigger installation and
missing intents. It labels pre-settlement intent state unknown when active orders
exist and gives preservation/reconciliation actions rather than automatic fixes.

Startup now refuses a missing/disabled durable publication migration. Health reports
consumer progress with additive readiness fields and never retries settlement,
clears a failure or changes orders. Historical missing observations degrade derived
readiness without inventing data or blocking committed financial settlement.
Files: `scripts/reconcile_restart.py`, `backend/stores/postgres.py`,
`backend/api/main.py`, `tests/integration/test_restart_diagnostics.py`.
Phase 5 verification: **21 passed** (diagnostics, order API and failure windows;
20.36 seconds). Health checks did not acknowledge outbox work or clear failures.

## Phase 6: actual production proxy validation

Phase 5 commit `e10cd8d` pushed and confirmed on origin.
The official Caddy binary **v2.11.9** was downloaded to the private temporary test
directory (no dependency or binary committed). Actual `caddy validate` accepts the
production configuration. A real Caddy process, production Next build and Uvicorn
run behind verified test TLS. Only test ports and an explicitly trusted local
certificate differ from the production configuration; public DNS/ACME issuance is
not claimed. Documentation references: [Caddy reverse proxy](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy),
[timeouts/global options](https://caddyserver.com/docs/caddyfile/options), and
[log filtering](https://caddyserver.com/docs/caddyfile/directives/log).

Caddy retains automatic TLS/redirects for a real configured DNS hostname, a single
canonical origin, BFF routing for all HTTP routes and direct upgrade only at
`/live/ws`. Runtime and access logs drop request headers, including ticket-bearing
subprotocols; access logs also remove Set-Cookie. Upstream WebSockets drop Cookie
and Authorization while retaining the offered ticket. Backend/Next bind loopback.
Caddy admin is disabled. Request/header limits and transport/idle/stream timeouts
are explicit. Uvicorn retains its 2048-byte frame limit, one owner and no access log.

Executable suite: `tests/integration/test_production_tls_proxy.py`; isolated owned
process harness `scripts/production_test_stack.py`; guarded test-only metrics/header
presence/fault injection app `scripts/production_test_app.py` refuses non-test DBs.
**1 passed** (13.60 seconds): HTTPS login, secure HttpOnly/SameSite session cookie,
HTTP redirect, foreign CSRF rejection, authenticated WSS, single-use ticket,
invalid/expired ticket, live logout revocation, BFF routing and observed upstream
credential stripping. Ticket values and injected credential canaries absent in logs.
Development proxy, authentication and frontend sources were not changed.

## Phase 7: measured capacity and bounds

Phase 6 commit `790e1cd` pushed and confirmed on origin.
`tests/benchmarks/test_websocket_capacity.py`: **4 passed**, 23.97 seconds.
Actual authenticated WSS clients at 10/50/100 connections, fresh-ticket reconnect
bursts, invalid-ticket attempts, slow receivers, crossing orders via the BFF,
private-event isolation and task release were exercised. Capacity credentials use
test-issued signed JWTs through the real internal ticket endpoint; signature,
single-use ticket, identity, origin and per-user validation remain active.
The separate TLS suite covers actual password login and browser cookies.

| Clients | Connect p95 ms | Notification p95 ms | Settlement p95 ms | Sample DB connections | Reconnect successes | Tasks after disconnect |
|---|---:|---:|---:|---:|---:|---:|
| 10 | 145.31 | 34.27 | 12.91 | 5 | 10 | 0 |
| 50 | 190.16 | 202.45 | 14.37 | 3 | 50 | 0 |
| 100 | 154.52 | 282.22 | 14.32 | 2 | 100 | 0 |

Includes intentionally slow receivers (max observed notification delay ~3.2 sec).
No dropped notifications in these short real-network cases. Deterministic 10,000-event
fanout overflow independently verifies the 128-item bound and fail-fast resync path.
Process RSS at measurement: backend ~103–112 MiB, Next ~135–145 MiB,
Caddy ~49–62 MiB. CPU samples include startup/bcrypt cost and are not sustained CPU
ceilings. Database/queue measurements are snapshots, not proof of peak capacity.
No claim is made about 1024 real connections or deployment on other hardware.
Existing authorization, queue sizes and matching rules were not relaxed.
Raw measured evidence: `docs/architecture/recovery-hardening-evidence/websocket-capacity.json`.

## Regression findings and recovery follow-up

Phase 7 commit `90ee04a` pushed and confirmed on origin.
The first full integration run found **2 failures / 135 passed**: the old exact
16-table expectation needed to include the additive outbox, and simulator derived
status still looked only at the initializer's volatile worker. Fixed the expected
17-table count and bridged persisted outbox retry status into the existing Neo4j
worker diagnostics without changing simulator behavior or authorization.
Focused rechecks: **8 passed** (schema, Neo4j outage, durable consumer recovery).

Startup and the operator script now share read-only invariant checks in
`backend/risk/restart_safety.py`. Startup refuses terminal volume, escrow, position,
archive identity, execution-reference or missing-publication mismatches as well as
active orders. It never repairs a mismatch. Additional checks cover a disabled
publication trigger and deliberately corrupted synthetic position.
Focused startup/API rechecks: **20 passed** (22.32 seconds).

Owner caveat: a session advisory lock excludes two healthy owners, but it does not
fence an already running financial transaction on a different connection if the
lease is lost. A full recovery protocol needs transaction-level owner generations
as well as durable admission/fill intents. No automatic active-order recovery or
claim of recovery from every torn-lease boundary is made in this change.
Follow-up verification: **12 passed** including an actual isolated child-process
`os._exit` immediately after financial COMMIT (intents and exact financial state
survive, duplicate settlement remains a no-op). **4 passed** for the final shared
restart diagnostics, including canonical order/trader/instrument/maker-price checks.

## Additional replay ordering verification

Recovery follow-up commit `63d70a4` pushed and confirmed on origin.
A complete backend run passed **421 tests** (184.23 seconds), including actual TLS
and capacity cases. Review then reproduced an additional uncovered failure: an old
regime event could replace a newer live/current capture in the same minute.

`20261117_regime_replay_ordering.sql` adds nullable observation time and canonical
execution tie-break metadata to the existing regime table, without changing its
vector, feature calculations, minute key or similarity query. Atomic upsert ordering
now covers both durable replay and live capture. Unknown historical ordering is
preserved and raises a retryable `ObservationOrderUnknown`; no timestamp is invented
for an existing row. A compatibility trigger timestamps only actual new writes from
a draining older writer. Startup/readiness require both reviewed migrations.

Files: new ordering migration, `scripts/migrate_recovery.py`,
`backend/stores/regimes.py`, `backend/stores/postgres.py`,
`backend/risk/restart_safety.py`, `tests/integration/test_outbox_recovery.py`.
Verification: the new regression failed before the fix with the old feature vector;
after the fix **25 passed** across durable observations, all polyglot consumers and
restart diagnostics, including preservation of unknown historical snapshots.
The isolated soak uses compatible additive migration during its run and loads the
updated worker on the planned backend restart; this is recorded as a limitation of
revision uniformity, not hidden as a single-revision benchmark.

## Reconnect storm follow-up

Observation-ordering commit `f34b82d` pushed and confirmed on origin.
Final full-suite attempt after that fix: **422 passed, 1 failed** (180.96 seconds).
The failure was `SSL: UNEXPECTED_MESSAGE` during the 100-client TLS reconnect burst,
before WebSocket authentication. No financial/auth invariant failed. The capacity
client now models bounded reconnect behavior (at most three transport attempts,
fresh single-use tickets and measured retry counts), without retrying certificate
verification failures or authorization rejections. Loopback tests explicitly avoid
system proxies. The cause of the transient TLS error is not asserted.

Focused remeasurement under concurrent soak load: **4 passed** (26.87 seconds),
no transport retries in that run. Connect p95: 151.17/349.77/348.24 ms at 10/50/100;
settlement p95: 38.25/22.46/24.12 ms. Higher latency than the initial measurement
illustrates shared-host load, not a guaranteed production ceiling. Raw second-run
evidence: `recovery-hardening-evidence/websocket-capacity-under-soak.json`.

## Final regression (phase 9, verification in progress)

Reconnect test commit `a08404a` pushed and confirmed on origin.
Final complete backend run: **423 passed**, 182.64 seconds, with actual Caddy TLS/WSS
and 10/50/100-client tests enabled. No skipped backend tests. The only warning is
an existing Starlette/httpx deprecation; dependencies were not changed.
Frontend `npm test`: **55 passed, zero skipped** with a dedicated isolated Redis
logical database. A first attempt at enabling those native tests was denied
loopback access by the tool sandbox (EPERM); rerunning with authorized network
access passed without source changes. `npm run typecheck`, `npm run format:check`
and `npm run build` all passed. Frontend source changes remain zero.

Additional ownership failure boundary: if an owner lease disappears while a
reservation is still uncommitted on a different connection, a new process may see
no active row yet. Current advisory ownership and snapshot checks cannot prove that
old transaction will never commit. This pre-settlement/torn-lease case remains
**unsafe/blocked**, not a verified automatic recovery guarantee. Implementing a
transaction-level owner fence and admission/fill journal is the precise wider
protocol work required. This branch does not enable active-order recovery.
Redis scope is also precise: existing version rejection is within an owner epoch.
A durable monotonic fence against an old writer after a torn lease requires the
same owner-generation protocol. Healthy ownership/shutdown and verified cold-start
paths are covered; cross-epoch torn-lease safety is not claimed by the cache alone.
Final separate commands so far: **206 unit tests passed** (2.11 seconds),
**141 integration tests passed** (115.92 seconds, real TLS enabled).
The remaining standalone concurrency command is running on the same final code.
Standalone concurrency completed: **68 passed**, 26.55 seconds. All four requested
backend regression commands and frontend verification have now been executed.

## Historical graph retention follow-up

Historical outbox delivery now explicitly preserves the existing 90-day inactivity
policy. It checks the canonical pair's latest trade before creating a relationship,
so backfill cannot recreate an expired pair after the startup retention pass.
Recent live delivery and the original `apply`/aggregate semantics are unchanged.
Focused checks: **22 passed** (durable recovery and all polyglot tests, 15.13 sec).
The test also checks that an old replay includes the exact all-history aggregate
when a newer canonical trade makes that pair active again.
Files: `backend/api/main.py`, `backend/stores/neo4j_graph.py`,
`tests/integration/test_outbox_recovery.py`; trailing blank line removed from the
new shared diagnostic module to satisfy the final branch diff check.
