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
