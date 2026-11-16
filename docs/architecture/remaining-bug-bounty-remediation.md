# Remaining bug-bounty remediation — 16 November 2026

## Baseline (Phase 0)

Branch: `codex/dbms-reliability-hardening`; starting HEAD:
`d29ae007b833963955c93aed82f14d2b4cb9184e`. Fetched and fast-forward checked;
working tree initially clean. Preserve cdd23ad, c95c541, 1457ccd and d29ae00.
Reviewed frontend/AGENTS.md (only repository AGENTS.md), schema, installer,
fixtures, prior hardening report, Coordinator and financial adapters.

Native PostgreSQL, Redis and Neo4j are available. Read-only checks found **three
active orders**, no matching-owner lock, and no API listening on port 8000.
No owner was started against that database. Existing financial data preserved.
Owner-instantiating suites require a separate synthetic database. Redis and graph
fixtures must retain unique instrument/trader scopes.

Baseline verification:
- Backend unit + concurrency: **225 passed**, one existing Starlette warning.
- Frontend tests: **32 passed**; typecheck and format check passed.
- Default Turbopack production build: **environment-blocked**, including escalated
  retry: CSS worker port binding returns EPERM. No source workaround applied.
- Initial sandbox-only native service checks/tests failed on connection permission;
  native baseline above was rerun with service access.

Commit/push: this section is committed as `docs(audit): establish remaining
hardening baseline`; exact SHA and confirmed push recorded in the next ledger update.

## Approval-gated persistence proposal (N-01, F-02)

Proposed supplementary `order_request_identity` table: primary key
`(trader_id, request_key)`, canonical SHA-256 request hash, reserved order ID,
original accepted response, acceptance timestamp. Keep identities after archival;
no cascading deletion or TTL. This is an additional table, **not yet approved or
implemented**. Files affected: reversible migration, reservation adapter/procedure,
Coordinator, orders routes, frontend submission state/client/allowlist/schema/form,
concurrency/integration/transport tests.

Financial invariant: acquire the key transaction lock, compare canonical validated
fields, reserve and insert identity in one PostgreSQL transaction; neither may commit
alone. Unique identity handles concurrent workers. Same payload returns the original
response without matching/reserving twice; changed payload conflicts. Ownership and
post-commit admission recovery must stay fail-closed; accepted reservation is not proof
that in-memory admission completed. Reconciliation must distinguish these outcomes.
Rollback: disable keyed admission/reconciliation, drain and reconcile in-flight work,
retain the identity table read-only while any key may be replayed. Dropping identities
is not a safe online rollback. No installer or live migration is authorized by this
proposal. Approval is required before implementation.

A crash-durable downstream outbox would be a separate approval: immutable execution
identity plus exact regime-book snapshot and per-consumer delivery state committed
at the correct financial boundary. Existing executions can reconstruct graph totals,
but cannot reconstruct a lost historical order-book snapshot exactly. No memory-only
recovery is described as lossless. Strong trader DB isolation likewise needs a trusted
identity boundary; a caller-set app.trader_id GUC alone is insufficient.

## Resolution matrix and remaining work

All entries below remain unverified unless an evidence section explicitly supersedes
them. FIXED requires focused tests, a commit and successful remote push.

| ID | Initial classification | Remaining work |
| --- | --- | --- |
| N-02 | NOT_VERIFIED | Executable-liquidity capacity estimator and pipeline proof (Phase 1) |
| N-01 | BLOCKED | Durable atomic request identity requires approval (Phase 2) |
| F-02 | BLOCKED | Safe authoritative unlock depends on N-01 (Phase 3) |
| F-03 | NOT_VERIFIED | Persist cancellation intent and reconcile owned status (Phase 4) |
| F-01 | NOT_VERIFIED | Async shared Redis sessions and failure tests (Phase 5) |
| F-04 | NOT_VERIFIED | Central validated origin/cookie configuration (Phase 6) |
| I-01 | NOT_VERIFIED | Audit and reduce proven unnecessary runtime grants (Phase 7) |
| I-02 | BLOCKED | Prove trusted trader DB identity boundary before claiming RLS isolation |
| I-06 | PARTIALLY_FIXED | Prior financial reconciliation; derived/restart recovery remains (Phase 8) |
| N-05 | PARTIALLY_FIXED | Prior committed-event classification; lossless recovery remains |
| A-04 | PARTIALLY_FIXED | Safe failure retained; verified controlled recovery remains |
| I-03 | NOT_VERIFIED | Bounded startup execution replay (Phase 9) |
| N-06 | BLOCKED | Active-order restart needs persisted matching/publication recovery contract |
| I-05 | NOT_VERIFIED | Bounded atomic scheduled archival (Phase 10) |
| I-04 | NOT_VERIFIED | Verified simulator ERROR recovery (Phase 11) |
| A-02 | NOT_VERIFIED | Bounded synthetic backoff; shared Coordinator remains |
| P-02 | NOT_VERIFIED | Preserve arbitrary direct-book IDs and historical duplicate detection (Phase 12) |
| P-03 | BLOCKED | Exact historical payload deduplication cannot be blindly evicted |
| P-04 | NOT_VERIFIED | Sparse integer Fenwick plus measured CPU/memory (Phase 13) |
| N-03 | NOT_VERIFIED | Consistent per-book depth snapshots (Phase 14) |
| P-07 | NOT_VERIFIED | Exact transaction-local cancellation fee reuse (Phase 15) |
| N-04 | NOT_VERIFIED | Replay-safe bounded canonical graph aggregation (Phase 16) |
| A-03 | NOT_VERIFIED | Opt-in bounded maintenance and retention (Phase 17) |
| A-01 | PARTIALLY_FIXED | Shared sessions, safe readiness/restart; active-active remains approval-gated |
| A-05 | NOT_VERIFIED | Execute and document existing SQL demonstrations (Phase 18) |

Final full suites, financial and browser acceptance, real performance measurements,
and final Git/remote audit remain Phase 19. No production deployment claimed.

Corrected findings remain intentional/accurate: head-of-queue STP cancels incoming
residual; randomized ReferenceBook differential coverage already exists;
price_level.py is an unused placeholder, not a proven runtime defect.

## Phase 1 — N-02 executable-liquidity capacity

Root cause: admission used every resting ID for queue capacity and sequence
allocation. Changed `backend/matching/order_book.py` to estimate compatible
opposite-side maker FIFOs on the requested instrument, stopping at the existing
head-STP boundary. The estimator is read-only, ignores quantity conservatively,
and never cleans lazy heaps. `backend/risk/order_reservation.py` uses the bound
before reservation and again before publication under the existing global lock.
No fee, pricing, FIFO, schema, or API change.

Tests added in `tests/unit/test_matching_engine.py`: 4,000 unrelated/noncrossing
orders, stale heap preservation, both sides, crossing/partial/multiple fills,
head-STP, exact capacity and insufficient capacity. `tests/integration/test_order_pipeline.py`
proves admission above total resting-order capacity with exactly one reservation
per request and exact escrow. **29 matching tests and 12 native isolated pipeline
tests passed** (existing Starlette warning). Isolated database is
`tradegraph_audit_20261116`, schema-only copy plus synthetic seeds; original data
was not copied or reset. Existing backpressure-before-reservation regression passes.

Disposition: FIXED upon this commit's successful push. Phase 0 commit `182ae97`
is confirmed pushed. Phase 1 commit is identified by subject
`fix(admission): estimate event capacity from executable liquidity`; SHA/push
confirmation follows in the next ledger update. Limit: upper bound may overcount
makers when incoming quantity is small, intentionally; depth estimation scan/sort
optimization remains Phase 14.

## Phase 2 — N-01 durable request identity (approved)

User approved implementation and isolated tests after reviewing the proposal.
`db/migrations/20261116_request_identity.sql` adds the supplementary identity table,
trader/key uniqueness, canonical hash checks, and SELECT/INSERT-only runtime grants;
generic roles have none. Original accepted response is reconstructible exactly from
order_id, accepted_at and constant OPEN. No order FK or TTL: archival retains identity.
Operator must adapt the default runtime-role grant if using a custom login.
The migration was applied **only to tradegraph_audit_20261116**.

`backend/risk/request_identity.py` separates canonical hashing/verification/lookup.
`backend/stores/postgres.py` serializes each full key using a transaction advisory
lock, verifies payload, and commits financial reservation and identity insertion
on the same connection/transaction. Existing reservation procedure already permits
this outer transaction; its financial mathematics/locks are unchanged. Coordinator
replaces the process-local 100,000-entry set with durable lookups, returning the
original accepted row without rematching. Conflicts remain deterministic 409.
Database errors remain fail-closed. The native simulator expectation is updated
to require original-response replay, and only synthetic fixture identities are
cleaned. Installer/schema verification permit the supplementary table while still
requiring all 13 core tables.

Exact affected files: migration, backend/risk/request_identity.py,
backend/risk/order_reservation.py, backend/stores/postgres.py,
backend/simulator/market_simulator.py, scripts/setup_backend.sh,
scripts/verify_schema.py, tests/concurrency/test_reservation.py,
tests/integration/test_order_pipeline.py, tests/integration/test_live_simulator.py.
Tests: **34 reservation/pipeline tests passed**, including concurrent duplicates,
fresh-adapter replay, conflict, independent traders, archival and injected identity
constraint failure after financial writes (complete rollback). An additional focused
simulator replay assertion is verified before commit.

N-01: FIXED on successful push. Phase 1 `4ceb575` confirmed pushed. This phase's
SHA/push confirmation follows next update. Limitation: no schema migration applied
to live service. Durable acceptance proves reservation, not crash-safe completion
of in-memory matching/publication. N-06 remains blocked; active-order startup still
refuses unsafe reconstruction. Rollback disables new keyed traffic and INSERT grant
while retaining identity rows for reconciliation; deleting identities online is unsafe.

## Phase 3 — F-02 authoritative submission reconciliation

Root cause: boolean sessionStorage gate had no authoritative resolution. Replaced
with scoped persisted intent states, saved original payload/key/time, and explicit
read-only reconciliation and same-key retry. No backend token enters storage.
Legacy v1 intents are retained and may be resolved by a matching durable key;
pre-migration unknown keys without saved payload remain operator-blocked safely.
A failed lookup or failed replay authentication never discards the earlier intent.

Changed backend/api/routes/orders.py (authenticated trader-only request outcome;
absence is UNRESOLVED), frontend/src/lib/api/{submission,operations,schema,client}.ts,
frontend/src/lib/{services,contracts}.ts and components/trader/order-form.tsx.
Strict forwarding allowlist/response schemas retained. Form loads pending state,
checks canonical outcomes, refreshes views, and offers explicit original-key/payload
retry. It never creates a fresh key for unresolved intent.
Tests: frontend/tests/transport.test.ts and tests/integration/test_order_pipeline.py;
**34 frontend tests + typecheck passed**. Native pipeline tests include a real
reservation COMMIT followed by injected lost acknowledgement: owned lookup and
same-key replay identify exactly one reservation; pipeline failure is not reset.
Final native result and format/build evidence recorded with commit verification.
F-02: FIXED for post-migration durable intents upon successful push; legacy
pre-migration unknown requests remain a documented limitation. Phase 2 `abcd4bf`
confirmed pushed; no live migration/deployment. N-06 and durable publication remain
separate constraints.

## Phase 4 — F-03 persistent cancellation reconciliation

Root cause: dialog-local uncertainty disappeared on remount. The cancellation
tracker in frontend/src/lib/api/submission.ts persists intent before dispatch,
with SHA-256 account scope and target ID in the key, retains unknown results and
blocks repeat cancellation. client.ts and cancel-dialog.tsx load persisted state
and expose a status check; account/order views refresh after verified resolution.
services.ts, schema.ts and operations.ts include strict typed owned status lookup.
A dedicated backend/api/routes/orders.py read-only lookup serializes behind the
Coordinator lock and settlement drain: paginated history alone cannot establish
that an earlier cancellation thread has completed. Missing owner/pipeline readiness
fails closed. Only authenticated trader-owned hot/history rows are returned.
No new schema or financial calculation. Tests in frontend/tests/transport.test.ts
and tests/integration/test_order_pipeline.py cover timeout/remount, duplicate
suppression, account separation, unavailable/wrong-owner status, terminal unlock,
owned API lookup and repeated cancellation with exactly zero second refund.
**35 frontend tests, typecheck and 14 native pipeline tests passed**. Format check
requires formatting Next's regenerated next-env.d.ts after the supported webpack
build; no runtime configuration change. F-03: FIXED upon push.

Phase 3 `c7b2948` confirmed pushed. Its 13 native tests and formatting passed;
`npm run build -- --webpack` compiled and generated all routes successfully.
Default Turbopack remains environment-blocked (EPERM); webpack is an existing
supported Next.js build option, not a production source workaround.

## Phase 5 — F-01 shared encrypted sessions

Replaced global session Map/cap with an asynchronous injectable SessionStore in
frontend/src/lib/server/session-core.ts. redis-session-store.ts uses one lazy,
reconnecting ioredis connection, bounded connection/command deadlines, no offline
queue and no local fallback. Opaque random 32-byte session IDs remain; Redis keys
use the dedicated frontend namespace and TTL cannot exceed actual backend JWT exp.
AES-256-GCM encrypts stored JWTs with per-session IV and key/ID-bound authentication.
SESSION_ENCRYPTION_KEY (32-byte hex) and REDIS_URL are mandatory server configuration;
rotation invalidates existing encrypted sessions. Production deployments require
Redis persistence/availability policy; Redis memory alone is not disk durability.

Affected: session-core.ts, new redis-session-store.ts, app/api/session/route.ts,
app/api/backend/[...path]/route.ts, frontend/package{,-lock}.json, .env.example,
frontend/tests/session.test.ts. session.ts already returns the async getSession
promise from its async readSession, so page authorization awaits shared storage.
Login/logout and 401 cleanup await revocation; store outages return controlled 503.
Original roles, expiry, HTTP-only browser cookie and token non-disclosure preserved.

Verification: session tests with injectable store verify expiry, role, multiple
sessions, failure behavior and revocation. **All four session tests passed with
native Redis**, including separate connections/restart-style store construction,
ciphertext inspection, real TTL expiration and cross-connection deletion. Full
frontend tests/typecheck/format results recorded before commit. npm installed
only ioredis (+8 transitive packages); audit reported zero vulnerabilities.
Client reconnect/timeout options checked against the maintained upstream docs:
https://github.com/redis/ioredis . F-01: FIXED upon push; production configuration
and end-to-end login acceptance remain deployment verification. Phase 4 `dd88cef`
confirmed pushed. No existing Redis keys deleted; only random test session keys.

## Phase 6 — F-04 trusted production origin

New frontend/src/lib/server/app-origin.ts validates the one origin used by cookie
security and CSRF. Production requires explicit HTTPS; HTTP is limited to loopback
and an explicit ALLOW_INSECURE_LOOPBACK_ORIGIN controlled-test override. Development
may use loopback HTTP. Credentials, paths, malformed URLs, whitespace, query and
fragment (including empty delimiters) fail closed. No incoming Host header controls
cookie security. HTTP-only and SameSite Strict preserved.
Changed session.ts, session-core.ts, both API routes, .env.example and session tests.
**37 frontend tests passed, one opt-in native Redis test skipped in the service-free
suite; typecheck and format passed**. That native session test previously passed
when explicitly enabled. Foreign/originless CSRF regressions remain passing.
F-04: FIXED upon push. Phase 5 `a2797f1` confirmed pushed, with full webpack build,
typecheck and formatting passed after resolving the TypeScript status-narrowing
check (no runtime behavior suppressed). No live configuration or service restart.

## Phase 7 — I-01/I-02 authorization boundary

Audit: reserve/settle/cancel use tightly scoped SECURITY DEFINER financial routines,
with EXECUTE denied to generic trader/admin roles. Authentication needs id/email/
password_hash/role; identity, graph and simulator need trader id/user_account_id/
desk_id/full_name. New migration 20261116_runtime_columns.sql and setup_backend.sh
replace broad direct identity-table SELECT with those column grants. Financial
read grants remain necessary for current matching/startup/analytics; NOINHERIT
and explicit transaction-local admin role remain. No trader identity GUC introduced.
Migration applied only to the isolated database; production grants unchanged.

New tests/integration/test_database_authorization.py verifies direct financial and
identity writes denied, narrowed columns, explicit admin context, missing context
failure, transaction-local role cleanup and generic financial EXECUTE denial.
Original pipeline tests cover body-identity rejection and owned status denial.
Schema regression now proves exactly the 13 original core tables plus the approved
identity table, rather than wrongly requiring only 13 total objects.

I-01: PARTIALLY_FIXED (narrower identity reads); I-02: BLOCKED for database tenant
isolation. A compromised shared service credential can still read other traders'
financial rows and explicitly SET ROLE compliance_admin_role. API identity filtering
is real authorization, not proof of DB tenant isolation. Full isolation needs separate
trusted trader/admin/financial credentials or a reviewed cryptographically bound
stored-procedure read boundary, plus rewritten query paths and deployment secrets.
That is a new architectural contract requiring approval; no speculative RLS policy
or credential rotation applied. Financial/SQL compatibility results follow before
commit. Exact affected files: migration, installer, authorization tests,
tests/integration/test_database_integrity.py and this ledger.
Verification: **39 isolated native authorization, pipeline and SQL integrity tests
passed**, one existing warning. Phase 6 `5db100c` confirmed pushed. No live migration.

### Phase 8 persistence boundary

Full crash-durable derived delivery remains approval-gated. Existing execution rows
reconstruct canonical graph totals, but not the original regime order-book snapshot
or callback acknowledgement progress. A supplementary outbox would need immutable
execution payload, original book snapshot, per-consumer acknowledgements, uniqueness
by execution/consumer, and atomic financial/outbox COMMIT. Replay must never
recapture a different snapshot as if original. Safe rollback retains undelivered
outbox rows and drains them before disabling delivery. This also affects restart
and accepted-but-unmatched order recovery; an execution outbox alone cannot solve
N-06. No outbox table is approved, no failure reset is implemented from these claims.

## Phase 8 — retained post-commit recovery (partial)

backend/events/dispatcher.py now distinguishes typed backlog, post-commit,
financial-uncertain and ownership failures, with a distinct temporary-capacity
exception. settlement_worker.py retains analytics-applied and successful callback
indices. Its internal recover_committed() requires the previous task terminated,
canonical execution equality, verified owner lock, exact engine event identity,
unchanged callbacks and healthy derived consumers. Only known atomic enqueue
callbacks may retry; successful callbacks are skipped. No committed event is
resettled. regime_worker.py retains the originally rejected event/snapshot tuple
through overflow so live-process retry cannot recapture a different book.
Coordinator.verify_owner() checks the actual advisory lock (including signed
64-bit key halves), not only connection liveness; admission and owned-order
reconciliation use it. No public reset endpoint or automatic failure clearing.

Tests/concurrency/test_settlement_recovery.py adds full-backlog refusal followed
by successful controlled publication with exactly one financial commit and one
analytics application. Existing native timeout, unknown COMMIT, exact/conflicting
replay, post-commit overflow and Neo4j outage regressions rerun with pipeline tests.
**27 native recovery/pipeline tests passed** before commit (one existing warning).
Initial lock-decoding defect was caught by pipeline tests and corrected; failures
were not suppressed. Phase 7 `66d5872` confirmed pushed.
I-06/N-05/A-04: PARTIALLY_FIXED. Retained live-process publication can recover;
process-crash delivery and active-order restart remain persistence limitations.
Cache snapshot overflow/admission failure is not reset by this method. Required
regime snapshots cannot be reconstructed from executions alone. No durable-outbox
or physical HA guarantee is claimed.

## Restart operating procedure (N-06)

Run `PYTHONPATH=. .venv/bin/python scripts/reconcile_restart.py` for read-only
counts, execution-volume mismatches and actual advisory-lock ownership. Do not
terminate an existing owner to obtain startup. Keep admissions closed while
reconciling a retained event; never cancel human orders just to satisfy startup.
Archive only terminal reconciled orders. A clean cold start acquires the sole
owner before replay and stays unready until replay completes. With active orders,
reconcile accepted reservations, FIFO, remaining quantity and outstanding matched
events under operator control before a planned drain; the process must still refuse
automatic reconstruction. Three existing active live orders are untouched.

## Phase 9 — I-03 bounded startup history

Database.execution_batches/iter_executions use a named server cursor in one
repeatable-read, read-only snapshot with validated batch size (default 1,000).
Startup fetches each batch off the owner loop, applies events in exact ID order on
the owner thread, tracks replay progress, and closes the cursor on interruption.
It no longer eagerly materializes all execution rows. Historical analytics/dedup
state still grows (P-03); bounded transport does not claim bounded total analytics.

New scripts/reconcile_restart.py is read-only and does not acquire ownership.
New tests/concurrency/test_execution_replay.py checks batch order, concurrent-write
snapshot exclusion, exact VWAP/volume, duplicate replay, invalid sizes and early
cursor close. **15 native replay/pipeline tests passed**, including clean restart,
second-owner rejection and active-order refusal. I-03: FIXED upon push; N-06 remains
BLOCKED by accepted-but-unmatched and publication persistence/FIFO recovery.
Phase 8 `79c75d1` confirmed pushed.

Read-only live diagnostic later observed zero active orders, 547 executions,
no volume mismatches and one owner lock (database changed externally during work).
It correctly reports cold_start_safe=false. No live ownership/data was changed by
this task. Unrelated auth-form.tsx changes and generated next-env.d.ts edits are
preserved and excluded from remediation commits.
