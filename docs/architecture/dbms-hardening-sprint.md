# DBMS reliability sprint — 16 November 2026

Started approximately 07:32 UTC; 60-minute maximum. Dedicated local branch
`codex/dbms-reliability-hardening`, based on integration commit 29a0185.
No push or merge authorized for this sprint. Initial working tree clean.

## Phase 0 audit and baseline

Reviewed schema, reservation, settlement, cancellation, position trigger, archival,
index installer, database adapter, financial/derived consumers and concurrency tests.
Reservation locks the account before reserving cash/escrow. Settlement locks event
ID, checks exact replay, locks accounts by UUID then orders by ID, inserts execution
(trigger recomputes rational position/PnL), applies cumulative rounded fees and
releases reservation in the same PostgreSQL transaction. Worker acknowledgement
occurs after COMMIT, then analytics and derived callbacks. Cancellation shares
account-before-order locking. Archival is one DELETE RETURNING / INSERT statement
with terminal-status and execution-volume reconciliation predicates.

Readiness found **three active orders**. The existing API owner was preserved;
no second owner, destructive database changes or human-order cancellation allowed.
Focused baseline (no matching owner instantiated):
`.venv/bin/python -m pytest tests/concurrency/test_settlement_locks.py tests/concurrency/test_reservation.py tests/unit/test_matching.py -q`
**119 passed**, existing Starlette/httpx warning, 14.87 seconds.

## Phase 1 — historical lookup indexes

Added order-ID indexes for cumulative fee and archival lookup, and composite
(trader, instrument, execution ID) indexes for both position-history sides.
No financial function, formula, table, constraint or privilege changed. Existing
trader-only indexes retained. Position replay remains O(relevant history); no
incremental accounting or persisted cost basis was introduced.

`PYTHONPATH=. .venv/bin/python scripts/benchmark_execution_lookups.py` executed
EXPLAIN ANALYZE BUFFERS on a 50,000-row temporary execution clone carrying existing
indexes, then the new indexes. Full before/after plans are committed under
hardening-evidence/. Measurements concern lookup paths, not total settlement cost.
The clone and generated rows are rolled back; no shared execution rows changed.

Native setup wraps ordinary index creation in a transaction. Its query_indexes.sql
remains compatible. Separate migration 20261116_execution_lookups.sql uses
CONCURRENTLY and MUST run outside a transaction wrapper. Reversal is documented;
interrupted/invalid or conflicting existing indexes require operator inspection.
**Migration not applied to the running exchange.** Existing financial concurrency
and long/short/PnL/fee partition/replay tests passed in the baseline above.

## Phase 2C — bounded transaction recovery

Only PostgreSQL transaction-abort SQLSTATEs 40001, 40P01, 57014 and 55P03 retry,
with the unchanged immutable event, maximum three attempts and bounded delay.
Connection/unknown acknowledgement failures are no longer blindly retried: an exact
canonical execution row (including timestamp, counterparties and taker invariant)
is required to acknowledge success. Absence, mismatch or failed reconciliation
retains the event and fails admissions closed. No new financial persistence.

Native recovery + original financial tests: **23 passed**, 11.63 seconds, existing
warning. Injection covers deadlock/serialization/statement/lock aborts after real
transactional financial writes and confirms rollback; additional tests induce real
PostgreSQL statement and lock timeouts. Lost acknowledgement after actual COMMIT,
absent/conflicting canonical records, three-attempt exhaustion, exact execution
count, cash, escrow, order quantities and position/PnL are checked. Original tests
cover concurrent replay, conflicting replay, weighted reversals, cumulative
single/many-fill fees and partial cancellation. No API owner instantiated.

## Phase 2D — separate committed settlement from publication failures

Worker tracks whether its retained event is already committed. A failed downstream
handoff attempts remaining independent callbacks, retains the event, explicitly
reports committed financial success with publication failure, and fails admissions
closed. It does not resettle or silently discard that event. Existing derived
worker retains/retries a failed Neo4j handler. No durable outbox/recovery guarantee
is claimed: pending queues and callback progress are process-local, and pgvector
capture is not inherently replay-idempotent. Operator reconciliation is required
for overflow; no automatic blanket re-publication was added.

Combined recovery, financial, reservation and matching run: **131 passed**,
18.07 seconds; existing warning only. Queue-overflow injection confirms exactly
one execution, unchanged fees/cash/escrow/PnL, remaining callback delivery, retained
committed event, failed admissions and idempotent canonical replay. Neo4j
ServiceUnavailable injection confirms retained derived retry and one settlement.

## Phase 3 — atomic archival verified, scheduler deferred

Added native regressions for partial-order exclusion, cancellation followed by
archival, canonical execution preservation, duplicate archive-key failure rolling
back the DELETE, a second connection attempting archival during uncommitted
settlement, and execution-volume mismatch exclusion. No production archival SQL
correction was needed. No scheduler or shared-data archival was introduced.
Existing execution order IDs intentionally have no FK to the active order table,
so executions survive a move into order_history. Existing instrument/trader FKs
remain intact. The new order lookup indexes support the reconciliation subquery;
no unmeasured archival candidate index was added.

## Final verification and disposition

- Full applicable no-owner regression command:
  `.venv/bin/python -m pytest tests/unit tests/concurrency tests/integration/test_database_integrity.py -q`
  **240 passed**, 27.69 seconds, one existing Starlette/httpx deprecation warning.
- After adding the explicit execution-volume guard and failed-admission assertion:
  `.venv/bin/python -m pytest tests/concurrency/test_archive_atomicity.py tests/concurrency/test_settlement_recovery.py -q`
  **16 passed**, 6.79 seconds, same warning. Counts overlap; do not sum them.
- Owner-instantiating API/live-simulator tests were not rerun: three preexisting
  active orders prevented a safe cold restart. Tests above use real isolated
  PostgreSQL transactions but do not acquire another matching owner.
- No diff to schema.sql, procedures, triggers, frontend or public API files.
  Existing financial locks, fees, exact rational PnL, reservation/cancellation
  boundaries, matcher ordering/STP, constraints, RLS and grants preserved.
- Only new SQL objects: four non-unique execution lookup indexes. Migration is
  additive/reversible and **not applied** to the active database. Only temporary
  clones were indexed for measurement. Production index build validation remains
  an operator deployment task; do not run the full installer on a busy exchange.
- Existing running API continues its originally loaded code. This sprint does not
  restart it or deploy the worker fixes while active human orders exist. Perform
  operator reconciliation/drain before a controlled restart. Frontend remains
  untouched. No push or merge performed.

Lookup-only EXPLAIN timings on 50,000 generated rows (milliseconds, single probe;
warmth/planning noise applies; not a throughput or asymptotic guarantee):

| Query | Before | After |
| --- | ---: | ---: |
| Fee/order lookup | 3.938 | 0.046 |
| Buyer position lookup | 0.254 | 0.066 |
| Seller position lookup | 0.121 | 0.027 |

Disposition:

| Item | Result |
| --- | --- |
| A: historical position scan | Index mitigation verified on clone; still replays relevant history. Rational computation unchanged. |
| B: fee history scans | Lookup indexes supplied; repeated cancel-order aggregation left unchanged to avoid financial procedure changes. |
| C: transaction-abort recovery | Bounded retries and exact canonical commit reconciliation verified. Unresolved outcomes stay closed. |
| D: post-commit exception classification | Fixed and tested; retained event, independent callbacks attempted, overflow fails closed. Lossless durable delivery remains unimplemented. |
| Archival | Atomic behavior verified; operational scheduling remains deferred. |

Modified files:
`backend/stores/postgres.py`, `backend/workers/settlement_worker.py`,
`db/queries/query_indexes.sql`, `db/migrations/20261116_execution_lookups.sql`,
`scripts/benchmark_execution_lookups.py`,
`tests/concurrency/test_settlement_recovery.py`,
`tests/concurrency/test_archive_atomicity.py`, this report and
`docs/architecture/hardening-evidence/execution-lookup-plans.json`.

Local verified fix commits: indexes `cdd23ad`, recovery `c95c541`, publication
classification `1457ccd`; archival regression/report commit follows this record.

Prioritized follow-ups (not rushed into this bounded sprint):

1. Durable order/event idempotency and recovery: needs persistence/architecture
   approval; current process-local queues cannot prove lossless crash recovery.
2. Controlled deployment: validate/apply online indexes, reconcile active orders,
   restart one owner, rerun full API/polyglot/live simulation suites. Existing
   activity makes that unsafe during this sprint.
3. Incremental exact position accounting: requires approved persisted rational cost
   basis/state and long/short/concurrency proofs; index changes cannot provide O(1).
4. Scheduled bounded archival: operator cutoff/batch/locking policy needs workload
   validation; current atomic query remains manually scheduled.
5. Trader-scoped RLS/privilege review: authorization-policy changes need separate
   review; current grants/policies were preserved.
6. Streaming history rehydration, Neo4j repeated-pair optimization and pgvector
   retention/HNSW tuning: need workload-specific measurements and replay/retention
   semantics; not necessary for the verified fixes above.
7. Sustained settlement benchmarks and redundant in-transaction fee aggregation:
   require longer representative runs and financial regression evidence. This
   sprint measured lookup plans only.

Passing these checks does not establish production readiness.
