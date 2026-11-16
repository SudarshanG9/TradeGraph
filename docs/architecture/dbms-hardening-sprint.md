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
