# Frontend, registration and live reliability implementation

Starting main: `ccd5374d018af95b4a71ca0540f6ebb3538c2181`.
Branch: `codex/frontend-live-registration-hardening`. Never merge automatically.

## Phase 0 — audit

Status: PARTIALLY_FIXED (audit complete; full native reproduction pending).

Confirmed in source: bootstrap catches every session failure and sets null;
`startPolling.refresh()` drops refresh while pending; dashboard `Promise.all`
couples three independent resources; signup creates no records; no live endpoint
exists. These source findings are not claimed as browser reproductions.

Inspected authentication/session/transport, all requested backend financial paths,
identity installer, schema and request/RLS migrations. Matching ownership and
COMMIT boundaries must remain unchanged. Registration needs an operator-owned
provisioner because HTTP credentials deliberately cannot create roles.

Tests added: `frontend/tests/session-recovery.test.ts` exercises store outage and
recovery without deletion and authoritative missing-cookie behavior.

Baseline: frontend 38 passed, 2 native Redis tests skipped; typecheck and formatting
passed. Production build failed because the environment denies a build worker
binding a port (Turbopack/PostCSS); native retry pending. Backend unit, concurrency,
and isolated native suites pending. No production dependency was restarted.

Existing uncommitted auth placeholder and generated Next types edits were preserved
while switching from the previous branch. Branch creation and initial push succeeded.
Commit SHA and test evidence are appended after each phase push.

## Acceptance policy

FIXED means tested behavior in the stated environment. PARTIALLY_FIXED means some
required behavior remains. BLOCKED identifies an unavailable dependency or unsafe
action. NOT_VERIFIED means no execution evidence. No UI mock or open socket counts
as full financial acceptance. Never run a second owner on the existing database.

Phase 0 commit: `27333d8`, pushed successfully. Backend unit baseline: 203 passed.
Isolated combined baseline: 257 passed, 1 failed, 33 fixture errors; investigating
fixture schema/environment gaps before interpreting these as product regressions.

## Phase 1 — canonical origin and CSRF

Status: FIXED for tested validator behavior; browser mismatch redirect deferred to
same-origin proxy phase. Original policy conflated every denial as CSRF_REJECTED.
Updated `app-origin.ts`, `session-core.ts`, `.env.example`, and session tests:
strict canonical URL syntax; distinct missing-header, missing-origin, foreign-origin,
cross-site and alternate-loopback error codes. Neither host headers nor a login
exception expands origin trust. HTTPS production and explicit loopback test policy
are preserved. Session cookies still derive security from the configured origin.
Tests: frontend suite/typecheck run in this phase; see following commit evidence.
No API/DB relationship changes. No production configuration changed.

Phase 1: 41 frontend tests passed, 2 native tests skipped; typecheck passed.
Commit `b049c88`, pushed. Baseline isolated fixture errors were missing dedicated
Redis (connection refused on 6391); a separate Redis server is now running there.

## Phase 2 — session initialization

Status: FIXED in controller regression tests; browser failure injection pending.
Files: `auth-state.ts`, provider, auth client, session recovery tests. Bootstrap now
has loading/authenticated/unauthenticated/temporarily_unavailable states, a retry,
and generation-based protection from stale checks following login/logout.
503/network/timeout/malformed session responses preserve unknown status and hide
protected content; only confirmed absence/401 redirects. BroadcastChannel and
visibility verification reconcile tabs without storing credentials in the browser.
Existing encrypted shared Redis session storage and non-deletion on outages remain.
Tests cover outage/recovery, absent/invalid cookies and stale completion after
login/logout. No DB or public API contract change. Native restart evidence pending.

Phase 2: 43 frontend tests passed, 2 native tests skipped; typecheck passed.
Commit `726d5f9`, pushed.

## Phase 3 — server rendering recovery

Status: PARTIALLY_FIXED until native browser retry verification.
Redis 503 from role-checking layouts previously escaped before child Retry existed.
Both protected layouts now render `ServiceUnavailable` only for typed session 503;
Next redirect exceptions remain untouched. Root `app/error.tsx` catches nested
layout failures (same-segment boundaries do not). Retry refreshes server rendering.
Files: protected layouts, server session helper, shared recovery view, root boundary.
No protected children render on unknown authorization. Raw error messages are not
shown. Verified against this installed Next version's error/proxy documentation,
which uses `retry` in error boundaries. Frontend suite and typecheck pass.
DB/API: unchanged. Server-render outage/recovery browser evidence pending.

Phase 3 commit `25b9fad`, pushed. 43 frontend tests passed, typecheck passed.

## Phase 4 — atomic registration

Status: FIXED for native persistence tests; provisioning is Phase 5.
Added registration state/policy tables and normalized-email uniqueness, a restricted
SECURITY DEFINER transaction, validated registration store/model, POST /register,
normalized login and readiness checks for both login and existing tokens.
Migration installer binds a dedicated auth role; rollback preserves pending states.
Default zero-funded pending verification; explicit synthetic policy supports fixed
starter funds without fake KYC. No existing core relationship or financial routine
changed. Documents: registration-operations.md. Tests: 20 concurrent distinct
accounts, normalized concurrent duplicates, required-insert rollback, bcrypt,
fee/funding/FKs, no fabricated verification, privilege/byte validation.
Native result recorded below after completion. HTTP rate limits follow in Phase 6.

Phase 4: 212 backend tests passed (203 unit, 9 native registration cases).
Commit `10e327f`, pushed.

## Phase 5 — database identity provisioning

Status: FIXED for native two-user concurrent/repeated provisioning tests.
New operator service and CLI reuse the private manifest installer and credential
validation. Credentials stage durably before role creation; a manifest lock plus
session advisory lock serializes reconciliation. Only eligible registration states
can transition ACTIVE, after independent SCRAM/session-user/membership/RLS/account
verification. Failure remains retryable. API never receives CREATEROLE/admin keys.
Files: trader_provisioning service, provision_registrations CLI, registration tests,
operations docs. No financial changes. Tests cover two parallel users, independent
margin access, cross-user denial, readiness and stable secrets on repeated provision.
Limitations: actual process-kill fault injection and thousand-user scale not yet
verified; recovery ordering is explicit and tested by repeat execution.

Phase 5: 10 native registration/provisioning tests passed. Commit `6a79f20`, pushed.

## Phase 6 — real signup integration

Status: PARTIALLY_FIXED pending browser multi-user exercise.
Replaced fake signup with validated async registration, strict request/receipt
contracts, public CSRF-protected BFF allowlist, pending status messages and disabled
repeat submission. Admin creation remains operator-only. Existing local auth email
placeholder change is preserved in this phase. Redis-backed hashed-key limits cover
login IP/account and signup IP; outages return 503, excess 429. No email delivery
provider is configured; no email or KYC verification is claimed. Ambiguous registration
uses normalized identity/login reconciliation instead of automatic retry.
Tests: 45 frontend passed, 2 native skipped, typecheck passed; abuse classification
unit test passed. Five-user browser signup is reserved for full-stack acceptance.
Files: auth route/limiter, frontend auth forms/page/client/contracts/schema/operations,
BFF route, registration and limiter tests. Financial HTTP mutation flow unchanged.

Phase 6 commit `64679b3`, pushed. Backend broad native regression still running;
all native failures will be classified before final acceptance.

## Phase 7 — nonblocking notification publication

Status: PARTIALLY_FIXED; authenticated transport is delivered with Phase 8.
Added validated v1 envelopes, bounded per-client queues, per-user/global caps,
private routing, market subscriptions, per-connection sequence and owner epoch.
A slow client overflows and must resynchronize; publication never raises into the
financial caller. Admission/cancel invalidations follow database commit; execution
invalidations attach to the existing settlement after_commit callback. No matching,
fees, financial SQL or settlement retry semantics changed. Simulator control
mutations notify admins. Files: live_protocol/live_bus, main, coordinator, simulator
routes and live bus tests. Unit tests prove privacy, sequence and queue limits;
real socket authorization and COMMIT tests follow with tickets. Notification
loss is handled by snapshots and polling; no durable event delivery claim.

Phase 7: 206 unit tests passed. Commit `adedaf2`, pushed.

## Phase 8 — authenticated WebSocket transport and BFF tickets

Status: FIXED for native socket tests; same-origin browser proxy follows Phase 9.
Added `/live/ws`, Redis GETDEL single-use 20-second tickets, session-scoped revocation,
strict Origin/subprotocol checks, heartbeat/idle/message limits, subscription
validation, sender timeouts, expiry/role/readiness rechecks and disconnect cleanup.
No JWT or ticket appears in a URL or negotiated secret subprotocol. Only tradegraph.v1
is negotiated. Next `/api/live/ticket` uses cookie session + CSRF and server JWT;
logout revokes private access, with active sockets checked every 10 seconds.
Redis authentication failures close live access; HTTP remains authoritative.
Files: websocket endpoint/ticket store, backend config/lifespan, BFF ticket/session
routes/live helper/schema, native socket tests. Tests exercise missing/reused/expired
and revoked tickets, foreign origins, malformed subscriptions, connection limits,
cleanup and committed two-user trade/account invalidations verified against SQL.
Slow-client queue bounds covered by unit tests. Cancellation cleanup corrected
following native TestClient disconnect failures. Results appended next phase.

Phase 8: 2 native WebSocket cases passed (multiple acceptance paths each),
45 frontend passed, typecheck passed. Commit `55618f3`, pushed.

## Phase 9 — same-origin edge

Status: FIXED for native HTTP/upgrade routing tests; full browser path follows.
Added a dependency-free loopback Node streaming HTTP/upgrade proxy and production
TLS Caddy example. Fixed Next/backend targets; every /api request goes to Next,
only /live/ws upgrades to backend. Socket cookies/JWT headers are stripped.
Wrong loopback ordinary GET navigation redirects safely to configured origin;
POST and foreign hosts are rejected. Tests verify actual HTTP and upgrade flow,
BFF preservation, canonical navigation and credential stripping. Caddy is absent:
production example is NOT_VERIFIED and must be validated on deployment.
Files: deploy/local-proxy.mjs/test, Caddy example, live-operations.md. No financial
or DB changes. End-to-end proxy ticket connection awaits complete startup workflow.

Phase 9: 2 real local proxy routing/upgrade tests passed. Commit `34730f7`, pushed.

## Phase 10 — shared browser live client

Status: PARTIALLY_FIXED pending authoritative snapshot synchronization (Phase 12).
One authenticated provider owns a connection, fresh-ticket reconnect with capped
exponential jitter, heartbeat watchdog, strict protocol decoding, per-connection
sequence/epoch gap detection, old book-version rejection, bounded canonical trade-ID
deduplication, explicit instrument unsubscribe/subscribe and generation-safe cleanup.
Logout/account changes close sockets; no financial mutation retry exists here.
Connection state stays resyncing until snapshots are acknowledged, avoiding false
'live' claims. HTTP polling remains enabled. Files: live client/protocol, live
provider, preview provider, live-client tests. Tests verify shared widget subscribers,
stale/order/gap handling, instrument switch, pending-ticket logout and bounded retries.
Frontend tests/typecheck pass; browser network failure exercise follows acceptance.

Phase 10: 47 frontend tests passed, 2 native skipped; typecheck passed.
Commit `168002e`, pushed.

## Phase 11 — deterministic loading and retry

Status: FIXED for polling regressions; browser partial-failure exercise pending.
Manual refresh during pending work now queues exactly one trailing request, with
completion promises; no overlap or dropped Retry. Scope cleanup aborts old work
and suppresses old results. Resource states distinguish initial load, refresh,
ready, stale and error; successful snapshots stay visible on recoverable failures.
Scope tags hide prior session/instrument data immediately. Dashboard account,
orders and trades load/retry independently; account fields remain one HTTP snapshot.
Files: polling, provider/resource hook, dashboard and polling tests. Tests cover
coalesced retries, cancellation, hidden views, bounded backoff/recovery and stale
completion suppression. 49 frontend tests passed, 2 native skipped; typecheck passed.
No financial POST is retried by polling. Resource registry prepares snapshot
acknowledgment without declaring an open socket synchronized.

Phase 11 commit `66ba2b3`, pushed.

## Phase 12 — authoritative live synchronization

Status: PARTIALLY_FIXED until browser two-user convergence acceptance.
Notifications invalidate registered authenticated HTTP resources. Reconnect/gap
resync stays delayed until successful snapshots complete; errors retain polling.
Periodic reconciliation covers missed notifications. Connected/synchronized views
use slower bounded polling, disconnect restores normal intervals. UI distinguishes
verified snapshot synchronization from delayed fallback. Trade IDs remain canonical
and bounded observed execution history remains unchanged.

Depth notifications now follow successful atomic Redis apply (worker-to-loop handoff),
preventing notification-before-cache races. HTTP book adds owner epoch and rejects
old-owner cached depth with 503 DEPTH_RESYNC_REQUIRED. Existing global version semantics
are preserved; version jumps across instruments are not misrepresented as missing
per-instrument events. Files: cache/lifespan/depth/market route, live/provider hooks,
contracts/schema/mock, terminal/shell indicators. 206 backend unit and 49 frontend
tests passed (2 native Redis tests skipped); typecheck passed. Native polyglot,
order-pipeline/socket regression is running. No change to financial arithmetic.

Phase 12: native socket/polyglot/order pipeline regression: 31 passed.
Commit `efde926`, pushed.

## Phase 13 — catalogue and admin recovery

Status: PARTIALLY_FIXED until per-endpoint browser injection checks.
Catalogue now has bounded recovery polling, explicit retry, scope cancellation,
validated active selection and clears unavailable metadata so trading cannot use an
unverified selection. It participates in reconnect snapshots. Protected content
remounts on explicit account-generation changes, clearing manual admin query state.
Admin query controls retain validated input and expose actual Retry submission;
existing request-generation checks protect instrument/fixture/scenario transitions.
Read-only desk/surveillance/health pages use shared resource error/empty/stale UI.
Files: provider and admin disclosure/optimizer/regime controls. 49 frontend tests
passed (2 native skipped); typecheck passed. Existing UI design preserved. Catalogue
and all admin failure-recovery browser evidence follows in acceptance.

Phase 13 commit `8abc9cd`, pushed.

## Phase 14 — integration classification and diagnostics

Status: FIXED for tested transport/security/snapshot cases; deployment audit remains.
Browser GETs now have bounded timeout/cancellation and typed malformed-response
errors; transport preserves 400/401/403/404/409/422/429/503/504. Financial ambiguity
still retains durable request keys and never automatically creates a new mutation.
Wrong credentials on public login no longer revoke a valid existing cookie; new
sessions are stored before deleting the old one. Logout can clear authoritatively
expired/disabled identity while service outages remain retryable.

Added safe bounded request correlation/status/duration/dependency logs using route
names (no bodies/query strings or secrets); live logs expose only connection state,
reconnect and gap counters. Retry-After is retained for backend rate limits.
Account balance and positions now use one repeatable-read RLS transaction; no
financial calculations or procedures changed. Files: backend diagnostics/main,
orders/store, BFF/session/live routes/client/transport/operations and tests.

Validation: 53 frontend passed, 2 native Redis skipped; typecheck passed. 40 native
authorization/registration/pipeline/socket cases passed. Additional interleaved
settlement/account snapshot regression and auth privilege checks recorded below.
Webpack production build passed; default Turbopack had an environment worker-port
restriction. Build regenerated Next type declaration formatting, normalized again.

Phase 14: 12 additional registration/privilege/account snapshot cases passed,
including settlement deliberately interleaved between balance and position reads.
Commit `4e76001`, pushed.

## Phase 15 — repeatable full-stack workflow

Status: FIXED for a clean isolated installation/startup; production TLS unverified.
Added a non-destructive preflight/lifecycle launcher and an explicitly NEW-directory
SCRAM PostgreSQL/dedicated Redis test installer. Preflight validates config, services,
migrations, private identities, cold-start diagnostics and ports before starting
one owner/Next/proxy. No seeds/migrations/cancellation occur in the launcher. Admin
credentials are stripped from child runtime environments. Pending registration does
not require already-provisioned credentials. New test installer alone opts into
synthetic funds and scopes Neo4j by newly generated trader identities.

The first clean install hit host disk exhaustion; removed only generated Next cache,
then installed successfully in a new directory. First working isolated stack was
gracefully stopped; clean installer-produced environment passed preflight and started
through the documented command. Discovered missing native Uvicorn WebSocket protocol
package (in-process tests do not need it); added/test-installed websockets 15.0.1.
Production build uses supported webpack and passes; preserves/normalizes existing
Next type-import edits. Schema verifiers allow only approved supplementary tables.
Files: create_test_stack/run_local/with_test_environment, requirements, schema/setup
allowlists, package/build, env example, root/frontend/identity deployment docs.
Private configs/logs remain under /tmp, never staged. Stop retains test data.

Phase 15 commit `b064bc8`, pushed.

## Phase 16 — real multi-user acceptance

Status: FIXED for the executed isolated scenarios; production/load limits below.
Five UI registrations plus fifteen real BFF registrations produced twenty distinct
ACTIVE, operator-verified RLS identities per run. Five concurrent browser contexts
logged in. The final Chrome run settled 61 crossing pairs with independent open
dashboards, periodic offline receivers and instrument changes. Account cash, escrow,
positions/PnL and filled orders matched canonical SQL; no resting residuals remained.
All eleven trader/admin routes loaded without browser exceptions.

Actual Redis stop/restart returned session/login 503 without cookie deletion or
false login redirect. Once the BFF reconnects, server-layout Retry restores protected
content. Same encrypted session survived a second Next instance and its restart.
A clean full-stack restart changed owner epoch and the existing browser reconnected,
refetched authoritative state and retained its account without navigation or login.
Invalid cookie, hostile origins, cross-user order reads and admin access were denied.
Independent account/orders/depth/trades/catalogue/surveillance/optimizer failures
recovered through Retry; unaffected widgets remained usable. Fifteen rapid instrument
changes converged to the selected book.

Acceptance found and fixed three integration edges: missing/old-epoch cache now
schedules a bounded authoritative depth rebuild; server-layout Retry also rechecks
client authentication; local preflight distinguishes TCP TIME_WAIT from a live
listener (bind/reuse plus listen). The last has a native regression test. Schema
assertions now explicitly include only the approved supplementary tables. Added
post-role-COMMIT provisioning failure/retry and active-socket revocation regressions.
Files: market route, shared unavailable UI, run_local, integration tests, three Chrome
harnesses and scoped operator fixture bridge. No financial procedure was modified.

Evidence: `live-hardening-evidence/browser-{acceptance,recovery,restart}.json` and
`settled-trader.png`. Final activity: 95,953 ms, 61 executions, 2,313 observed live
frames; publication-to-Chrome receipt median 5 ms, p95 25 ms, maximum 518 ms.
First submission-to-verified-screen: 1,024 ms (includes SQL assertions and browser
test overhead). These are one local run, not an SLA or an isolated rendering benchmark.

Validation: complete backend suite 388 passed before two extra security regressions
and the port regression; targeted security suite 15 passed, native port test 1 passed.
Frontend 55 passed, zero skipped (native Redis enabled); typecheck/format passed.
Three final browser reports passed. Earlier failing harness runs were retained in
private /tmp logs; races in readiness/element/URL waits were corrected, not hidden by
weakening application checks. Extended run initially clicked before BFF reconnect;
final check waits for actual session endpoint readiness before testing Retry.

Limitations: 96-second controlled trading run is not a prolonged capacity soak.
Production TLS/Caddy, per-process memory growth, production failure-rate/latency SLOs,
and hundreds/thousands of roles remain NOT_VERIFIED. Queue bounds, slow-consumer
overflow and simulator dependency gates are regression-tested; no production Neo4j
service was stopped. Native scoped Neo4j/pgvector integration and browser surveillance
recovery passed. Default production registration remains PENDING_VERIFICATION until
a real operator verification workflow is supplied; no KYC verification is invented.

Phase 16 commit `642ac0f`, pushed.

## Phase 17 — final regression and security audit

Status: FIXED for measured local acceptance; deployment/scale limits remain explicit.
Security review found heartbeat sends were not covered by the existing five-second
event-send timeout. Applied that bound to heartbeat and acceptance, with client-slot
cleanup on handshake failure. Added a native deliberately blocked heartbeat test.
Final complete backend run: **392 passed**, one Starlette/httpx deprecation warning,
117.75 seconds. Frontend: **55 passed**, zero skipped; typecheck/format passed;
production webpack build passed. Native proxy: **2 passed**. Final Chrome recovery
smoke against rebuilt frontend/final backend: all seven checks passed, no exceptions.
Prior multi-user/Redis/frontend/full-stack restart acceptance reports remain retained.

Tracemalloc bus measurement: 100 connections, 128 messages each, all overflow at
the bound; full queue allocations 3,761,146 bytes, post-cleanup delta 34,954 bytes.
This excludes socket buffers/ASGI tasks/process RSS and is not a capacity or leak
proof. Final report and sanitized evidence: `final-fullstack-acceptance.md` and
`live-hardening-evidence/`. Reviewed branch diff: core schema/financial procedures
unchanged, no private env, manifest, password or token artifacts staged.

The final isolated HTTP stack was cleanly stopped after acceptance. Test databases
and dedicated Redis instances remain preserved for inspection, with private config
under /tmp. No production service was stopped.
