# Final recovery and production hardening

Base: `9c4c64ded6f7129460eca8ff0e810dc60be09e84`.
Branch: `codex/final-recovery-production-hardening`.
Only durable recovery and production transport/stability are in scope.

## Final disposition

Work is committed on `codex/final-recovery-production-hardening`; `main` was not
merged or rewritten. Committed publication/replay and measured transport/stability
are implemented. Full automatic crash recovery is **not** declared complete.

| Requirement | Final outcome |
|---|---|
| Durable committed-event recovery | Verified after canonical execution COMMIT; financial transaction and intent are atomic |
| Downstream replay safety | Duplicate/retry/rebuild paths verified under known ownership; torn-lease remote-writer fencing remains BLOCKED |
| Active-order restart | Safely refused; durable admission/fill journal and owner-generation protocol required |
| PostgreSQL financial consistency | Verified by 424 backend tests and independent SQL accounting audits during both soaks |
| HTTPS reverse proxy | Real Caddy validator and trusted TLS environment verified; public DNS/ACME/firewall NOT_VERIFIED |
| WSS authentication | Real TLS ticket reuse/expiry/revocation and upstream stripping passed; origin checks also covered |
| Secure session cookies | Verified over actual HTTPS; existing session/CSRF implementation unchanged |
| WebSocket resource limits | 10/50/100 actual clients measured; bounded queues, reconnects, privacy and cleanup checked |
| Sustained load | Two completed >30-minute runs, 3623.74 seconds cumulatively, 3163 executions; second included deliberate slow reader |
| Restart/reconnection recovery | All five controlled interruptions recovered; terminal/archived startup verified; active-order and torn-lease guarantees blocked |
| Frontend/backend regressions | 424 backend and 55 frontend tests passed; typecheck, format check and production build passed |
| Scope preservation | No frontend/auth/session/provisioning/matching/fee/API-contract/financial-procedure/dependency redesign |
| Git commits and pushes | Every tested phase pushed; full SHA/file ledger and final remote verification below |

The remaining blockers are explicit protocol work, not permission failures:
persist accepted admission/matching turns, ordered pending fills and STP/cancel
progress, then fence old financial and derived writers with durable owner generations.
Historical regime inputs/order that were never recorded remain unavailable and are
preserved as diagnostics. No automatic cancellation, rematching, balance repair or
health-triggered recovery is implemented.

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

## Phase 8: measured sustained operation

Historical-retention commit `abc94f9` pushed and confirmed on origin.
First measured run: **PASS, 1813.43 seconds, 1581 executions, 3162 BFF orders**.
Three real browsers: 516 successful refreshes, 14,350 frames, zero recovery errors.
All five planned interruptions recovered. Independent SQL audit: 320 snapshots,
all 1581 canonical executions checked, exact fee/cash/escrow/position/PnL invariants.
Final fixture publication backlog, financial mismatches, active orders, duplicate
IDs, socket clients/tasks and settlement queue were zero. No financial failure.

The first run was a rolling metadata/worker recovery exercise. Review also found
that its slow-receiver index no longer existed after splitting ten connections
into seven raw clients and three browsers. That gap is explicitly recorded rather
than presented as success. The harness now delays raw client 6 and a second complete
1800-second run with that receiver and all interruptions is underway. The historical
retention follow-up affects only replay of events older than 90 days; all current
soak trades continue through the existing recent-event path. Revision uniformity
limitations are recorded in the results instead of hidden.

Files: `scripts/stress_test_live_stack.py`, `scripts/stability_browser.mjs`,
`scripts/monitor_stability_accounting.py`, `docs/architecture/live-operations.md`,
`docs/architecture/production-stability-results.md`,
`recovery-hardening-evidence/stability-rolling-30min.json` and
`recovery-hardening-evidence/accounting-rolling-30min.json`.
Private runtime files, credentials, certificate keys and raw request logs stay in
owner-only temporary directories and are never committed. The configured source
financial database was used only for a read-only collateral check (canonical graph
pairs present); fault injection and financial test writes remain isolated.


## Final regression and scope checkpoint

Phase 8 evidence commit `9c4fe6a` pushed and confirmed on origin.
After the historical-retention follow-up, the complete backend suite passed
**424 tests in 182.63 seconds** with actual Caddy TLS/WSS and capacity enabled.
No backend tests were skipped. The separately requested commands also passed:
206 unit tests, 68 concurrency tests, and 141 integration tests before the final
retention regression (which passed separately and in the final full suite).
All 55 frontend tests passed with native isolated Redis enabled, and type checking,
format checking and the production build passed. No frontend source was changed.

The final branch diff check passes. Every changed path is recovery persistence,
recovery consumers/startup diagnostics, the production edge, isolated verification,
or the required reports/evidence. The diff contains no changes to frontend source,
authentication/registration/session/CSRF implementations, trader provisioning,
matching/FIFO/STP rules, fee or financial SQL procedures, API submission/cancel
contracts, graph relationship types or vector feature/similarity mathematics.
The only existing baseline test expectation changed is the additive table count.

Full crash safety remains deliberately qualified: healthy-owner serialized replay
and verified terminal restart paths are tested. Durable admission/fill journaling
and transaction-level owner-generation fences are still required for uncommitted
financial work and late old writers after a torn lease. Session advisory locks are
not a distributed fence for remote writes already in flight. This limit applies
across financial connections and derived Redis/Neo4j projection writers; it is not
presented as fixed by the outbox. No automatic active-order recovery is enabled.


## Completed final slow-receiver run

Final regression checkpoint `fc0826b` pushed and confirmed on origin.
Second sustained run: **PASS, 1810.30 seconds, 1582 executions, 3164 BFF requests**,
with intentional slow receiver 6 and all five scoped interruptions. Three browsers:
516 successful refreshes, 14,375 frames, zero recovery errors. No order errors or
cross-user private events; 258 successful socket connections; final clients,
socket tasks, settlement queue and all financial/publication mismatch counts zero.
Independent auditor: 354 snapshots, all 1582 execution records, exact final cash
plus escrow 36,836 (= 40,000 minus 3,164 fees), zero escrow, net position sum and
realized PnL. Notification p95 includes the slow reader (6064.07 ms); financial
transaction p95 remained 36.07 ms across 622 samples since backend restart.

Combined runs: **3623.74 seconds, 3163 executions**. They are separate operational
runs, not an uninterrupted hour or a deployment-specific capacity guarantee.
Full timings, resource samples, tail latency and revision limitations are in
`production-stability-results.md` and the final/rolling evidence JSON files.
All test servers, browsers and the two isolated PostgreSQL/Redis stacks were
stopped after read-only checks confirmed no active owner or unresolved orders.
Private credentials, certificate keys and raw logs were not committed.


## Final Git and file ledger

Second-run evidence commit `ed070fe` was pushed and the remote tip was read back as
the same full commit. All preceding phase commits are ancestors of that remote tip.
The final documentation receipt is identified by remote HEAD and the final response.
No force push, shared reset/rebase or merge into main was performed.

| Full commit SHA | Phase/change | Push |
|---|---|---|
| `60dd9d8f02f4db94a491fbf1b00324a185621ceb` | test(recovery): characterize crash windows and restart invariants | Confirmed |
| `a8449a18021d1d3190f6b58ad8434f4e0b886bab` | feat(recovery): persist committed event publication intent | Confirmed |
| `12f55c3a989a9af834cdf16740762a88a0da04f9` | fix(recovery): make derived consumer replay safe and idempotent | Confirmed |
| `293b35d8530f29ef23485811dc48e7e03db592eb` | test(recovery): preserve safe refusal of ambiguous active matching state | Confirmed |
| `e10cd8d6b20e907c10dbc718e0add949687144ac` | test(recovery): verify durable replay and safe restart diagnostics | Confirmed |
| `790e1cd8988abea0571cf181a8f45bad54e6da56` | security(deploy): validate production HTTPS and WSS proxying | Confirmed |
| `90ee04a5d063df9b9df5011eada40e8e2fe66a77` | test(performance): verify bounded WebSocket capacity and recovery | Confirmed |
| `63d70a4d08cecc754154ab59b584cd34c9418b93` | fix(recovery): expose durable retries and enforce restart invariants | Confirmed |
| `f34b82da9f9e1284432c753dbbb0867837b1cd50` | fix(recovery): preserve observation order across live capture and replay | Confirmed |
| `a08404a772ab1b0cf6774c75860b1110d2e7bee1` | test(performance): measure bounded reconnect transport recovery | Confirmed |
| `abc94f938f6319570a56539af479aa868a308f72` | fix(recovery): preserve graph retention during historical replay | Confirmed |
| `9c4fe6a4e6d1e8f5cbc25f2721dcdf14402ba23a` | test(stability): verify sustained multi-user operation and recovery | Confirmed |
| `fc0826b8b59d3a21bef0dc8b27c36f8c3f9dd0bb` | test(reliability): record final regression and scope verification | Confirmed |
| `ed070fe95f9df4c0f98ac18566559df76185640a` | test(stability): record final slow-consumer recovery measurements | Confirmed |

Exact changed files for every committed phase:

<details><summary>60dd9d8 — test(recovery): characterize crash windows and restart invariants</summary>

- `docs/architecture/final-recovery-production-hardening.md`
- `tests/concurrency/test_recovery_windows.py`

</details>

<details><summary>a8449a1 — feat(recovery): persist committed event publication intent</summary>

- `backend/events/durable_outbox.py`
- `backend/workers/outbox_worker.py`
- `db/migrations/20261117_durable_event_outbox.sql`
- `docs/architecture/final-recovery-production-hardening.md`
- `scripts/migrate_recovery.py`
- `scripts/verify_schema.py`
- `tests/concurrency/test_durable_outbox.py`

</details>

<details><summary>12f55c3 — fix(recovery): make derived consumer replay safe and idempotent</summary>

- `backend/api/main.py`
- `backend/events/dispatcher.py`
- `backend/stores/postgres.py`
- `backend/stores/regimes.py`
- `backend/workers/graph_worker.py`
- `docs/architecture/final-recovery-production-hardening.md`
- `scripts/create_test_stack.py`
- `tests/integration/test_outbox_recovery.py`

</details>

<details><summary>293b35d — test(recovery): preserve safe refusal of ambiguous active matching state</summary>

- `docs/architecture/final-recovery-production-hardening.md`
- `tests/concurrency/test_active_order_restart.py`
- `tests/integration/test_matching_restart.py`

</details>

<details><summary>e10cd8d — test(recovery): verify durable replay and safe restart diagnostics</summary>

- `backend/api/main.py`
- `backend/stores/postgres.py`
- `docs/architecture/final-recovery-production-hardening.md`
- `scripts/reconcile_restart.py`
- `tests/integration/test_restart_diagnostics.py`

</details>

<details><summary>790e1cd — security(deploy): validate production HTTPS and WSS proxying</summary>

- `deploy/Caddyfile.example`
- `docs/architecture/final-recovery-production-hardening.md`
- `scripts/production_test_app.py`
- `scripts/production_test_stack.py`
- `tests/integration/test_production_tls_proxy.py`

</details>

<details><summary>90ee04a — test(performance): verify bounded WebSocket capacity and recovery</summary>

- `docs/architecture/final-recovery-production-hardening.md`
- `docs/architecture/recovery-hardening-evidence/websocket-capacity.json`
- `tests/benchmarks/test_websocket_capacity.py`

</details>

<details><summary>63d70a4 — fix(recovery): expose durable retries and enforce restart invariants</summary>

- `backend/api/main.py`
- `backend/risk/restart_safety.py`
- `backend/stores/postgres.py`
- `backend/workers/graph_worker.py`
- `backend/workers/outbox_worker.py`
- `docs/architecture/final-recovery-production-hardening.md`
- `scripts/reconcile_restart.py`
- `tests/concurrency/test_durable_outbox.py`
- `tests/integration/test_database_integrity.py`
- `tests/integration/test_restart_diagnostics.py`

</details>

<details><summary>f34b82d — fix(recovery): preserve observation order across live capture and replay</summary>

- `backend/risk/restart_safety.py`
- `backend/stores/postgres.py`
- `backend/stores/regimes.py`
- `db/migrations/20261117_regime_replay_ordering.sql`
- `docs/architecture/final-recovery-production-hardening.md`
- `scripts/migrate_recovery.py`
- `tests/integration/test_outbox_recovery.py`

</details>

<details><summary>a08404a — test(performance): measure bounded reconnect transport recovery</summary>

- `docs/architecture/final-recovery-production-hardening.md`
- `docs/architecture/recovery-hardening-evidence/websocket-capacity-under-soak.json`
- `tests/benchmarks/test_websocket_capacity.py`

</details>

<details><summary>abc94f9 — fix(recovery): preserve graph retention during historical replay</summary>

- `backend/api/main.py`
- `backend/risk/restart_safety.py`
- `backend/stores/neo4j_graph.py`
- `docs/architecture/final-recovery-production-hardening.md`
- `tests/integration/test_outbox_recovery.py`

</details>

<details><summary>9c4fe6a — test(stability): verify sustained multi-user operation and recovery</summary>

- `docs/architecture/final-recovery-production-hardening.md`
- `docs/architecture/live-operations.md`
- `docs/architecture/production-stability-results.md`
- `docs/architecture/recovery-hardening-evidence/accounting-rolling-30min.json`
- `docs/architecture/recovery-hardening-evidence/stability-rolling-30min.json`
- `scripts/monitor_stability_accounting.py`
- `scripts/stability_browser.mjs`
- `scripts/stress_test_live_stack.py`

</details>

<details><summary>fc0826b — test(reliability): record final regression and scope verification</summary>

- `docs/architecture/final-recovery-production-hardening.md`
- `docs/architecture/recovery-hardening-evidence/regression-summary.json`

</details>

<details><summary>ed070fe — test(stability): record final slow-consumer recovery measurements</summary>

- `docs/architecture/final-recovery-production-hardening.md`
- `docs/architecture/production-stability-results.md`
- `docs/architecture/recovery-hardening-evidence/accounting-final-30min.json`
- `docs/architecture/recovery-hardening-evidence/stability-final-30min.json`

</details>


Final checks: working tree clean before this documentation receipt; branch diff
passes `git diff main...HEAD --check`; all changed paths reviewed for the two issues.
Final stability evidence contains synthetic metrics only. Private credentials,
certificate keys and raw request logs remain outside Git. Both isolated native
service stacks were stopped after owner/order safety checks. Main remains at the
verified base commit; the final push and remote-tip equality are checked again
after committing this report.
