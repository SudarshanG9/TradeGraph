# Full-stack acceptance — 17 November 2026

Branch: `codex/frontend-live-registration-hardening`.
Baseline main: `ccd5374d018af95b4a71ca0540f6ebb3538c2181`.

## Outcome and scope

**PASS for the recorded isolated acceptance scenarios; not a production-readiness certification.**
Twenty newly registered traders were provisioned with independent PostgreSQL/RLS
identities in the final browser run. Five independent browser contexts logged in;
two traded while separate dashboard tabs remained open. Sixty-one crossing pairs
settled, screens converged to canonical SQL, and recovery succeeded after network,
Redis, frontend and complete-stack interruptions. No existing deployment database
was reset, no human orders were cancelled, and no second matching owner was launched.
Main was not merged or modified.

The phase-by-phase record is [frontend-live-registration-hardening.md](frontend-live-registration-hardening.md).
The retained evidence contains synthetic data only:

- [Trading, registration and dependency recovery](live-hardening-evidence/browser-acceptance.json)
- [Independent resource and administrator recovery](live-hardening-evidence/browser-recovery.json)
- [Full-stack restart and owner-epoch recovery](live-hardening-evidence/browser-restart.json)
- [Final-build recovery smoke](live-hardening-evidence/browser-final-security-smoke.json)
- [Bounded-queue allocation measurement](live-hardening-evidence/queue-memory.json)
- [Settled trader screenshot](live-hardening-evidence/settled-trader.png)

## Initial defects and corrections

| Defect | Correction and verification |
| --- | --- |
| Alternate localhost origin appeared as generic CSRF failure | One validated canonical origin, precise error codes, safe GET redirect; foreign/originless/cross-site mutations still denied |
| Session 503 became false logout | Explicit authentication state and generation guards; cookie retained, protected content hidden, Retry restores authentication |
| Server role-check failure prevented page recovery | Typed layout fallback plus parent error boundary; Retry refreshes both server route and client session |
| Signup did not persist identities | Transactional account/trader/margin/status creation, normalized uniqueness, honest pending receipt and operator provisioning |
| Dropped refresh while request pending | One queued trailing refresh, cancellation/scope guards, explicit initial/ready/refreshing/stale/error states |
| One failed API blanked dashboard | Independent account/orders/trades resources and individual Retry |
| No authenticated live delivery | Single-use ticket, authenticated bounded socket, commit-after notifications and authoritative HTTP reconciliation |
| Depth eviction could remain unavailable until a later mutation | Wrong/missing owner epoch returns 503 and queues a bounded authoritative cache rebuild |
| Port preflight rejected a clean restart | TIME_WAIT-safe bind/listen check still rejects a real listener |

Final security review also bounded socket acceptance and heartbeat sends to five
seconds and released the live-client slot on handshake failure. Ordinary event
sends already had the same timeout. A deliberately blocked heartbeat regression
checks cleanup; this closes a gap in the original slow-receiver bound.

## Registration, provisioning and migrations

The thirteen core relational tables and financial procedures are preserved.
`20261116_user_registration.sql` adds `registration_state`, `registration_policy`,
a normalized unique email index and a restricted account-creation function. The
existing `order_request_identity` supplementary table is retained. Conflicting
normalized emails require explicit operator resolution; no account is deleted.

The public auth identity cannot create roles, bypass RLS, write margin accounts or
self-assign administrator/funding/KYC fields. Registration atomically creates a
TRADER, trader row, STANDARD margin account and pending status. No fake KYC record
is inserted. Real deployments default to PENDING_VERIFICATION and zero funding;
only explicit synthetic policy enabled test funding and PENDING_PROVISIONING.
Passwords are normalized/validated appropriately and hashed with bcrypt; login
checks actual registration readiness after password verification.

A separate operator workflow serializes the private credential manifest and role
creation using file and PostgreSQL advisory locks. It stages durable credentials
before role COMMIT, verifies SCRAM (including wrong-password rejection), restricted
membership and actual forced-RLS access, then marks ACTIVE. Failed verification
leaves FAILED_RETRYABLE. Native tests prove retry after role COMMIT preserves the
same secret and account. The public API never receives operator credentials.

Application and nondestructive rollback commands are in
[registration-operations.md](registration-operations.md) and
[database-identity-deployment.md](database-identity-deployment.md). Rollback disables
new registration but preserves accounts, status and uniqueness; it does not erase
financial data.

## Session, WebSocket and API architecture

Browser session cookies are HTTP-only, SameSite strict and secure for HTTPS origins.
JWTs remain server-side in shared AES-GCM encrypted Redis records. A second frontend
instance and its restart read the same session. Expired/missing/invalid sessions are
authoritative absence; dependency failure remains 503 and never deletes cookies.
Financial POSTs retain existing durable request keys and ambiguous-outcome recovery.

CSRF-protected `POST /api/live/ticket` uses the BFF-held JWT to mint a twenty-second,
single-use Redis ticket, bound to the session hash and token expiry. `/live/ws`
requires the exact configured Origin and sends the ticket only as a subprotocol;
it never appears in URLs and is not echoed. Private invalidations use authenticated
identity; subscriptions accept only bounded active instrument IDs. Logout revocation
is rechecked on an existing socket within the heartbeat interval.

The single-process bus is best effort, with 4 connections/user, 1,024 global,
128 messages/connection, 8 instrument subscriptions, rate/frame/send/idle limits.
Book notifications follow successful versioned cache application; executions and
private account/order invalidations follow committed state. Events have owner epoch,
per-connection sequence and timestamp. No financial balances are trusted from events.
A shared browser connection detects stale/gap/epoch changes, reconnects with a fresh
ticket, fetches snapshots and declares synchronization only after successful reads.
Bounded polling continues as fallback and periodic reconciliation. Current event
handling conservatively invalidates all mounted resources; selective optimization
is deferred.

Contract additions: `/register` receipt/status; `/live/ticket`, `/live/revoke`,
`/live/ws` and BFF `/api/live/ticket`; book `epoch`; precise registration/readiness,
CSRF, dependency and depth-resynchronization codes. Existing error classes
400/401/403/404/409/422/429/503/504 and backend Retry-After are preserved. Account
cash/escrow/positions now share one repeatable-read RLS transaction; an interleaved
settlement regression verifies coherent snapshots. Safe diagnostics record route,
status, correlation, duration and connection/reconnect/gap state, not credentials.

## Validation and reproduction

Native regression used a separate SCRAM cluster on 55433 and dedicated Redis 6391,
with no running HTTP matching owner. Browser acceptance used the clean installer
cluster on 55434, dedicated Redis 6392, Next 3001, API 8000 and public proxy 3000.
Neo4j fixtures were scoped; the shared service was not stopped. The documented
installer created only a new test database/directory and did not touch default data.

| Check | Result |
| --- | --- |
| Complete backend suite before final review | 388 passed; then provisioning/revocation suite 15 passed and native port test 1 passed |
| Final complete backend suite | 392 passed, 1 deprecation warning, 117.75 seconds |
| Frontend tests, including native Redis | 55 passed, zero skipped |
| TypeScript and Prettier | Passed |
| Production webpack build | Passed |
| Real local HTTP/WebSocket proxy tests | 2 passed |
| Chrome multi-user trading/Redis/frontend restart | Passed, 14 recorded checks and 11 routes |
| Chrome independent API recovery/instrument switching/invalid cookie | Passed, 7 recorded checks |
| Chrome full-stack restart | Passed; changed epoch, same session/account, automatic resynchronization |
| Diff whitespace and tracked credential review | Passed; only environment examples, no private manifest/env/password/token artifacts |

Backend full regression includes unit, concurrency, matching, settlement, durable
requests, authorization, registration, simulator, PostgreSQL invariants, Neo4j and
pgvector integration. The single warning concerns Starlette's deprecated httpx
TestClient adapter, not a failed test.

Use the documented new-test installer and private env first. Never run regression
fixtures or browser registration against an existing financial database. Representative
commands (substitute PRIVATE_ENV and PRIVATE_ADMIN_FILE from the new installer):

```sh
.venv/bin/python -m scripts.with_test_environment --env-file PRIVATE_ENV --admin-password-file PRIVATE_ADMIN_FILE -- .venv/bin/python -m pytest -q
# Start browser stack only in a separate isolated database with no other owner:
.venv/bin/python -m scripts.run_local --env-file PRIVATE_ENV
.venv/bin/python -m scripts.with_test_environment --env-file PRIVATE_ENV --admin-password-file PRIVATE_ADMIN_FILE -- node frontend/tests/live_browser.mjs
.venv/bin/python -m scripts.with_test_environment --env-file PRIVATE_ENV --admin-password-file PRIVATE_ADMIN_FILE -- node frontend/tests/recovery_browser.mjs
```

The browser harness needs Playwright (`TRADEGRAPH_PLAYWRIGHT_MODULE` supports an
installed module directory) and Chrome (`TRADEGRAPH_CHROME_EXECUTABLE`). The scoped
Redis interruption only permits the documented test ports 6391/6392 and verifies
the private PID file. Every full trading run creates twenty new synthetic accounts;
rate limiting remains enabled. Wait for the limit window or use a fresh isolated
environment when repeating many runs; do not weaken production rate limits.

`restart_browser.mjs` additionally requires `TRADEGRAPH_STACK_PID` and
`TRADEGRAPH_TEST_ENV_FILE`; it verifies the exact supervisor command, stops only that
stack, starts it through normal preflight and shuts it down after acceptance.

```sh
cd frontend
TRADEGRAPH_TEST_REDIS_URL=redis://127.0.0.1:6391/0 npm test
npm run typecheck
npm run format:check
npm run build
# Build regenerates next-env.d.ts; normalize with the repository Prettier rules.
node --test ../deploy/local-proxy.test.mjs
```

## Measured performance and limits

Final browser run: **61 executions**, **95,953 ms** controlled activity,
**2,313** observed event frames. Publication-to-Chrome receipt: median **5 ms**,
p95 **25 ms**, maximum **518 ms**. First order submission through SQL and open-screen
verification: **1,024 ms**. All are local-host wall-clock/browser measurements and
include harness overhead, not production SLOs. Six periodic receiver interruptions
plus a separate outage recovered; the eleven route navigations had zero failures
and monitored pages reported zero uncaught browser exceptions.

API failure-rate denominators, process memory growth, long-duration soak performance
and reconnection latency distributions were not instrumented. A Python tracemalloc measurement with 100 synthetic connections used 434,430
allocated bytes after connect and 3,761,146 bytes with all queues at 128 messages;
all 100 overflowed at the bound. After disconnect/collection, 34,954 bytes remained
above baseline. This measures bus/queue allocations only, excluding TCP buffers,
ASGI tasks and total process memory; it is not a leak or server-capacity proof. Do not infer production throughput or a zero failure rate from this run.

## Correctness matrix and remaining limitations

| Capability | Evidence/status |
| --- | --- |
| Genuine multi-user registration and per-user RLS | PASS: twenty independent ACTIVE identities, normalized concurrent duplicates, rollback and provisioning retry tests |
| Login, CSRF and session recovery | PASS: real cookies/origins, Redis outage, second frontend, expiry/invalid-cookie tests |
| Protected layouts/dashboard/Retry/catalogue | PASS: individual browser fault injection and recovery |
| Authenticated bounded WebSockets | PASS: native invalid/replayed/expired/revoked tickets, subscription/connection limits, private event routing, slow queue/send bounds |
| Committed live trading and reconciliation | PASS: SQL/screen comparisons, offline receiver, changed owner epoch and resynchronization |
| Simulator | PASS in lifecycle/native regression; dedicated simulator browser soak NOT_VERIFIED |
| Redis | PASS: actual dedicated stop/restart and cache rebuild |
| Neo4j | PASS: scoped committed graph/replay/retention tests and real surveillance Retry; whole-service outage not injected |
| pgvector | PASS: real generation/similarity/retention/RLS/FTS tests |
| Financial correctness | PASS for regression and fixture scenarios; matching arithmetic and stored settlement procedures unchanged |
| Local deployment | PASS: clean installer, preflight, one owner, full-stack restart |
| Production deployment/security | PARTIALLY_VERIFIED: TLS/WSS/Caddy, secret rotation/backups, external abuse controls and capacity require deployment verification |

Other boundaries: registration is not an email/KYC verification service; operator
provisioning remains required. Credential manifests and PostgreSQL per-trader roles
need measured scaling/backup plans. Events have no durable outbox/replay guarantee;
HTTP/SQL is authoritative. Cold restart with active/unresolved orders is deliberately
refused and needs operator reconciliation, never automatic cancellation. Local test
Redis trusts loopback; real deployment must configure authenticated private services.
Default Turbopack was blocked by this execution environment's worker-port restriction;
the supported webpack production build is explicitly selected and passed.

## Commit and push record

Each implementation phase below was committed and pushed separately to the requested
branch. No force-push or merge was performed. Final audit/report receipts follow in
the living report and Git history.

| Commit | Change |
| --- | --- |
| `27333d881dc19158b9e87deb2825eba5ac398e06` | test(frontend): reproduce authentication loading and synchronization failures |
| `b049c885506615c04cdab6c30682142c94edfd6a` | fix(auth): stabilize canonical origin and CSRF validation |
| `726d5f9b33cefd43cfef374c7b119305dbdce87c` | fix(session): distinguish temporary unavailability from expired login |
| `25b9fadd5ca0e160a0a6b907c4d26cff6984603c` | fix(frontend): recover protected routes from temporary server failures |
| `10e327f2b5805fb0b051412919a27e2d558ff760` | feat(registration): create atomic multi-user trading accounts |
| `6a79f201980aeb89206e5b3c3c65de085352cfe8` | feat(identity): provision isolated database access for registered traders |
| `64679b34975f63bfb3774ccb6541de918ed61e35` | feat(frontend): connect signup forms to real account registration |
| `adedaf24cad648cc5a68952c214dcd0b9d30e37a` | feat(realtime): introduce nonblocking backend live event publication |
| `55618f378a2bf722da851296d765cd8b40a807bd` | security(realtime): authenticate WebSockets through single-use BFF tickets |
| `34730f74665888a6c54cf24b0d15a1360acd45f2` | infra(proxy): provide same-origin HTTP and WebSocket routing |
| `168002ebab59103c887fc5f3f47e3386f6bcffaa` | feat(frontend): add resilient shared real-time WebSocket client |
| `66ba2b375140bc6111c1f3b778f7f2ad0e57ccdb` | fix(frontend): make resource loading and retries recoverable |
| `efde926cec7790076f2153b5d850f61b8d7b4984` | feat(realtime): synchronize financial and market views from authoritative state |
| `8abc9cd925be68847742d4fbf92233a24caa2360` | fix(frontend): recover catalogue and administrative page data |
| `4e76001add136e5a2931990e727403c98aec247f` | fix(integration): standardize API failure handling and diagnostics |
| `b064bc88c5cba79094c571ba39cb25b7e112ca44` | infra(dev): provide reproducible full-stack startup and configuration checks |
| `642ac0f52d695f29a1029ad9d4e6b6a5b6ad0cb7` | test(e2e): verify multi-user registration and resilient live trading |
