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
