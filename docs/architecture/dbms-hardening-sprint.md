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
