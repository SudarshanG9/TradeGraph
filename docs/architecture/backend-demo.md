# Batch B backend acceptance report

Date: 15 November 2026. Repository: TradeGraph, branch main. Batch A base:
`1452a6f8153cff2a531564c8fb28f30c46a09e20`. User approved Phases 2–11, exact
BUY/SELL accounting, one matching owner and the non-durable academic queue, and
subsequently authorized a separate commit/push after every passing phase.

Result: backend implementation complete for final review, subject to the explicit
accepted limits below. Exact final checks are recorded below. No Docker,
frontend implementation, database reset, extra authoritative store or fourteenth
production table was introduced.

## Acceptance matrix

| Component / source requirement | Implemented behavior and evidence |
|---|---|
| ER, keys, constraints, native roles | original schema/ER unchanged; native verifier checks 13 tables, 18 FKs, generated FTS, VECTOR(6)/HNSW, both NOLOGIN app roles and forced RLS |
| ACID reservation | original secure SQL retained; real two/eight-client overspend, rollback, overflow, tick/lot and fee tests |
| Matching | original Order/Fill/MatchResult/OrderBook interfaces, heaps/FIFO/node index and STP preserved; original four 2,000-order differential sequences remain unchanged |
| Complete admission serialization | asyncio lock spans reservation→commit→matching→handoff; PG owner lease rejects another process; committed-row visibility checked from another connection |
| Fenwick / prefix VWAP | exact sparse coordinate BIT and true N+1 cumulative-prefix ring, wraparound/reference tests; settled event dedup; startup rehydrates committed history |
| FastAPI / authentication | all 14 contracted routes have Pydantic response/OpenAPI models, strict integer order bodies, bcrypt, expiring role JWT, server-resolved trader identity and stable error codes |
| Runtime database security | dedicated NOINHERIT/non-superuser service login; narrow routine grants; generic trader roles cannot write money or call unbound definers; admin effective native role plus SET LOCAL context |
| Settlement and cancellation | one SQL transaction for execution/accounts/orders/PnL, deterministic account/order locks, immutable event replay no-op/conflict checks, rollback and concurrent replay tests |
| Approved fees | exact R(q) release, BUY advances with terminal reconciliation, cumulative SELL actual fee from proceeds, variable price/role/fee-tier and 100-partial-fill SQL tests |
| Gross position PnL | exact rational weighted-average recomputation, long/short/partial close/flip, half-away-from-zero final storage; fees excluded, no invented cost-basis column |
| Events / consumers | financial commit precedes analytics/derived consumers; bounded queues; retained retries and failure/backpressure denial; repeated request cancellation waits for the database thread, and shutdown drains admission/in-flight writes before owner release |
| Advanced SQL | persisted order-book view; HAVING; recursive guarded rollup; ten-minute RANGE VWAP; UNION/INTERSECT/EXCEPT; nested/correlated subqueries; atomic scoped terminal archival |
| Redis | Lua atomic top-20 price-sorted sides, exact quantity hashes, eviction, version/freshness, native outage/recovery and rebuild tests |
| Neo4j | only Trader/EXECUTED_AGAINST; source uniqueness constraint; MERGE updates, canonical aggregate replay/rebuild, ring 3–5 candidates, scoped retention; actual committed three-trader ring |
| pgvector / FTS | actual six engineered features, minute UPSERT, HNSW cosine query, scoped retention, generated tsvector/GIN ranked search; API and native RLS denial tested |
| Normalization / data models | worked FD/Armstrong/1NF→BCNF→4NF proof, valid hypothetical examples, honest generated-column exception; exact Redis/graph/vector metadata and authority documented |
| Simulator | real native services via ASGI HTTP; deterministic multi-instrument fills, concurrent reservations, role/negative cases, conservation/PnL, replay, graph/vector/text/SQL, archive, clean restart and scoped cleanup |
| Performance | actual core/algorithm median/p95/p99 with hardware/warmup/sample counts, real EXPLAIN plans, explicit gated graph proof and separate native settlement/end-to-end timings |

All assertions above refer to executed tests in the phase ledger, not planned
stubs. Existing empty package markers remain valid; unused reference_matcher.py
and price_level.py placeholders are not filled with duplicate implementations
because the working reference oracle and linked price level already exist.

## Validation and measured results

Per-phase commands/counts, initial diagnosed failures and repairs are retained in
[backend-implementation-progress.md](backend-implementation-progress.md). Full
optimizer JSON and timing methodology are in [query-optimization.md](query-optimization.md).
Models/proofs: [backend contracts](backend-contracts.md),
[polyglot models](polyglot-data-models.md), [normalization proof](normalization-proof.md),
[existing ER/data dictionary](../er/tradegraph-er.md).

The Phase 10 full native run passed 189 tests with zero failures/skips. Final
Phase 11 checks, including contract, safe-installer and cancellation additions,
are recorded below. One upstream Starlette/httpx deprecation warning was observed;
it does not disable tests or change results.

Representative measured core values on Apple M1 / Python 3.13.0:

| Operation | Samples | Median |
|---|---:|---:|
| One-fill core match | 5000 | 2.250 microseconds |
| Known-node cancellation | 5000 | 0.333 microseconds |
| Fenwick range (65,536 coordinates) | 2000 | 0.875 microseconds |
| Direct range scan | 2000 | 291.125 microseconds |
| Prefix-ring VWAP (4096 fills) | 2000 | 0.917 microseconds |
| Independent VWAP rescan | 2000 | 286.292 microseconds |
| Native settlement including connection/transaction | 20 | 6.201 milliseconds |
| ASGI order pair → committed execution | 20 | 28.862 milliseconds |

The graph gate stayed closed while 2000 matches completed. With injected 50ms
per graph job, sampled core timing remained in the recorded microsecond range
and derived shutdown drain increased from 15.214ms to 994.288ms. Distributions
vary with shared CPU scheduling; this proves direct architectural separation,
not statistically identical runs or a guaranteed SLA. ASGI measurements exclude
external TCP/client latency. Tiny vector datasets may use a sequential scan.

The standalone simulator, seed 20261115, observed 18 executions, 39 archived
orders, 3 accepted/5 rejected race requests, 67 minor units of actual assessed
fees, one surveillance candidate and three regime matches. Independent Fraction
calculations checked every owned balance and gross position PnL. Original user,
margin, position and instrument row fingerprints were unchanged after cleanup.
The full concrete final scenario output is appended as JSON below (fresh CLI run after the final contract fixes).

## Native operational runbook

Use the existing .venv and .env. Configure PostgreSQL administrator socket/user
separately from runtime login credentials, plus actual Redis and Neo4j endpoints.
Never overwrite a working .env with its example. Secrets are ignored and never
returned by API health or simulation reports. Settings redact secret diagnostics.

For an initialized database:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
bash scripts/setup_backend.sh --phase 5
python scripts/verify_schema.py
uvicorn backend.api.main:app --host 127.0.0.1 --port 8000 --workers 1
```

The incremental installer checks the exact table set, preserves an installed
reservation function, installs dependent financial routines/triggers/grants/view
and compatible indexes. A new login may receive a generated missing/placeholder
secret. An existing login requires its current password and is never reset or
promoted. Invalid identity flags cause refusal. Missing/invalid JWT keys for the
new API are generated only in ignored .env. Repeated installation is safe for
existing rows; no seed, truncate, reset or schema bootstrap runs.

Fresh database setup remains separate and explicit: the user selects/creates an
empty native database and runs the original setup_day1.sh and interactive demo
seeder, then the incremental installer. This run did not create a disposable
replacement database or test destructive fresh bootstrap against existing data.
The original 18 Day 1 tests keep their marker; advanced SQL tests are not part of
fresh Day 1 selection.

Stop a separate API owner before running isolated API tests or the simulator:

```bash
python scripts/run_simulation.py --seed 20261115 --report /private/tmp/tradegraph-demo.json
python -m pytest tests/unit -q
python -m pytest -m day1 -q
python -m pytest tests/concurrency tests/integration -q
python -m pytest tests/benchmarks -q
python -m pytest -q
```

The simulator owns generated identities, instruments, keys, graph nodes and
snapshots; it checks counterparties before cleanup. It never deletes existing
user rows by name prefix or resets a database. Rollback fixtures and optimizer
lab leave no production test rows. Sequences can advance normally and are never
reset. APIs expose OpenAPI at /openapi.json; known invalid/expired JWTs return
401, wrong role 403, validation 422, funds/replay/terminal conflicts 409, unhealthy
financial processing or unavailable projections 503.

## Operator reconciliation and crash boundary

No durable outbox exists in the frozen ER. On a process crash, some raw matched
but unsettled fills may be unrecoverable. Stop new admissions; startup refuses
any unresolved OPEN/PARTIAL order. PostgreSQL atomicity means a recorded execution
committed its financial/order/position effects together, or the whole transaction
rolled back. A lost acknowledgement is retried only under the SAME immutable
execution ID/payload; never invent a replacement ID to replay a financial transfer.

Inspect under administrator control, read-only first:

```sql
SELECT id,trader_id,instrument_id,side,quantity,filled_quantity,status
FROM public."order" WHERE status IN ('OPEN','PARTIAL') ORDER BY id;
SELECT id,buy_order_id,sell_order_id,price_ticks,quantity,executed_at
FROM public.execution ORDER BY id DESC LIMIT 100;
SELECT trader_id,cash_balance,escrow_balance FROM public.margin_account;
```

Compare each remaining order's immutable limit/quantity/fixed fee basis with
R(q), execution history and pooled escrow. Independently retained, verified
immutable events may be replayed through settle_execution; same payload is a
no-op after commit, conflicting payload is rejected. If an event is gone, do not
claim its original matching order/prices are reconstructible. An operator can
explicitly choose cancellation of identified remaining reservations through
cancel_order(order_id,trader_id), in a transaction and with parameter binding,
after reviewing the financial facts. Never blanket-refund the pooled account or
automatically rematch all OPEN rows. Rebuild derived stores only after reconciliation.

The optional Idempotency-Key cache is process scoped and separate from execution
IDs. It rejects same-trader repeated keys before reservation, but it is not durable
after restart. Keyless equal orders remain distinct legitimate orders. All trading
remains subject to the financial failure/backpressure gate.

## Remaining limitations and unmet original requirements

- **Unconditional no-event-loss/crash durability: NOT MET, explicitly accepted.**
  The bounded queue is for the academic demonstration. No persistent outbox,
  message-delivery exactly-once guarantee or automatic missing-event recovery.
- **Next.js, UI screenshots and recorded full-project demonstration: NOT IMPLEMENTED.**
  Frontend was expressly excluded and remains unchanged; final full-course
  interface/demonstration compliance is incomplete.
- **Production exchange/margin/custody/scalability guarantees: not claimed.**
  Both sides reserve cash and synthetic shorts are permitted. No fee-revenue
  ledger or stored cost basis was added. Historical PnL recomputation, seen-ID
  memory and startup history hydration grow with history. One owner only.
- **Immutable demo fee/tick bases:** rate/assignment/tick/lot edits are rejected;
  mutable historical schedules need a separately approved model.
- **Exact adapter bounds:** Redis price score <=2^53−1; Neo4j notional aggregate
  <= signed BIGINT. Overflow is rejected, never silently rounded.
- **Finite queue capacity:** admission reserves a conservative fill bound from
  resting-order count. Large books/backlogs can return 503; this is not unbounded
  throughput or horizontal scaling.
- **Timing/generalization:** limited local hardware/sample sizes, in-process ASGI
  end-to-end timing, approximate HNSW and illustrative feature normalization.
  No unmeasured sub-millisecond Redis or universal index speedup claim.
- **Fresh clean-room bootstrap:** existing initialized native setup and rerunnable
  incremental install were verified; no new database was created to rerun Day 1.

No backend component is represented by a no-op success stub. Native services are
required by integration tests; missing dependencies are not silently skipped.
The final report lists any failures still present. Source PDF's frontend/Git steps
were interpreted through the user's explicit backend/native/Git instructions.

## Source/rubric traceability

| Original source | Evidence |
|---|---|
| Day 1 / Unit 1 ER, DDL/ALTER/DROP, seed, roles | original schema/ER, native verifier and original Day 1 tests; source scratch DROP remains intact |
| Day 2 risk and pure matching | original reservation races and differential tests; pure matching/analytics modules |
| Day 3 API/JWT/commit ordering/analytics/HAVING | API tests, typed contracts, BIT/prefix ring and grouped query |
| Day 4 settlement/PnL/view/recursive/window/set/archive | actual transactional/concurrent tests, SQL files and API rollup/optimizer |
| Day 5 Redis/Neo4j create/update/delete/query | actual native polyglot tests, scoped retention/rebuild, live ring |
| Day 6 vector/FTS/RLS/normalization/optimizer | actual UPSERT/search/delete/RLS tests; proofs/models and actual EXPLAIN JSON |
| Day 8 backend integration and latency proof | deterministic simulator, original-data fingerprint, gated real graph and measured benchmarks |
| Day 7–8 Next.js and final recording | deliberately pending separate frontend task |

## Phase commits and Git workflow

Each passing phase was committed and pushed only after the user's later explicit
Git authorization. Earlier no-Git instructions remain historical in the Batch A
record. No force push, history rewrite, reset, database reset or unrelated file
staging was used.

| Phase | Commit |
|---|---|
| 2 | ab3185d |
| 3 | 773a588 |
| 4 | ada6298 |
| 5 | ff4dde4 |
| 6 | d50e703 |
| 7 | 6e2ad43 |
| 8 | 068fecb |
| 9 | 9e83383 |
| 10 | c508848 |
| 11 | final documentation/acceptance commit follows this report; see Git log/final handoff |

## Final executed checks

```text
Final full suite:
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -q
192 passed, 1 warning in 51.69s
Failures: 0. Skips: 0.

Original Day 1 selection:
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -m day1 -q
18 passed, 174 deselected, 1 warning in 2.26s

New installer/OpenAPI contract checks:
2 passed, 1 warning in 1.61s

python scripts/verify_schema.py:
24 PASS checks; DAY 1 READ-ONLY VERIFICATION PASSED

bash scripts/setup_backend.sh --phase 5:
exit 0; existing reservation preserved, runtime grants/financial dependencies/view/indexes installed idempotently

bash -n scripts/setup_backend.sh scripts/setup_day1.sh:
exit 0

git diff --check:
exit 0
```

Native PostgreSQL 17.12 (Homebrew): fsync=on, synchronous_commit=on,
full_page_writes=on. Base counts after scoped cleanup: 4 users, 3 traders,
3 instruments, 0 active-table orders, 0 executions. Dedicated runtime role flags:
LOGIN true; SUPERUSER, INHERIT, CREATEDB, CREATEROLE, BYPASSRLS all false.
Runtime connections use a 30-second statement timeout and 10-second lock timeout;
these connection settings do not alter the server's global configuration.
The final cancellation regression delays acknowledgment after a real reservation
commit, cancels the request twice and verifies that ownership remains held until
the database thread completes. The uncertain admission fails closed, and a new
owner refuses the unresolved order pending operator reconciliation.
Observed Python packages: FastAPI 0.163.0, Uvicorn 0.54.0, PyJWT 2.15.1,
psycopg 3.3.8, redis 7.4.1, neo4j 6.4.1. Native Redis 8.10.2 and Neo4j
2026.09.0 were verified in prior phase evidence.

A real single-worker Uvicorn server ran on localhost:8765, returned the JSON below,
and shut down cleanly after the smoke test. Native datastore services were left
running. No trading order was placed by this unauthenticated smoke test:

```json
{
  "url": "http://127.0.0.1:8765",
  "health": {
    "status": "ok",
    "dependencies": {
      "postgres": "up",
      "redis": "up",
      "neo4j": "up",
      "regimes": "up"
    },
    "trading_ready": true
  },
  "openapi_paths": 14,
  "unauthenticated_own_orders": 401,
  "unauthenticated_admin": 401,
  "unauthenticated_order": 401
}
```

Git baseline/current frontend trees are identical:
`f78b5e6a429c1893b260c7eca85016b994ff6b43`. Original db/schema.sql,
docs/er/tradegraph-er.md, matching/order_book.py, matching differential tests and
reservation tests have no diff from Batch A. AST comparison confirmed all original
Day 1 integrity assertion bodies are unchanged; only marker placement changed.
No new architectural, environment or financial blocker remains for the bounded
backend demonstration. The accepted durability/UI limits above remain unmet
original full-project guarantees, not hidden passes.


## Concrete final simulator output

```json
{
  "seed": 20261115,
  "transport": "in-process ASGI HTTP; real native PostgreSQL/Redis/Neo4j",
  "crash_durable": false,
  "executions": 18,
  "financial": {
    "total_assessed_fees_minor": 67,
    "accounts": [
      {
        "trader_id": "88103dea-2344-4d71-b251-64a264dd8e97",
        "cash_balance": 956622,
        "escrow_balance": 0
      },
      {
        "trader_id": "bba9ad2e-ab6d-4b71-9a68-6096d3fe699e",
        "cash_balance": 1015116,
        "escrow_balance": 0
      },
      {
        "trader_id": "c8170613-fd19-4e92-8cc9-f8f16dbedf4c",
        "cash_balance": 1028195,
        "escrow_balance": 0
      },
      {
        "trader_id": "8520ac00-925e-4831-9fd6-e86c52bf1a0a",
        "cash_balance": 100000,
        "escrow_balance": 0
      }
    ],
    "positions": [
      {
        "trader_id": "bba9ad2e-ab6d-4b71-9a68-6096d3fe699e",
        "instrument_id": 269,
        "net_quantity": -95,
        "gross_realized_pnl": 0
      },
      {
        "trader_id": "bba9ad2e-ab6d-4b71-9a68-6096d3fe699e",
        "instrument_id": 271,
        "net_quantity": -30,
        "gross_realized_pnl": 0
      },
      {
        "trader_id": "88103dea-2344-4d71-b251-64a264dd8e97",
        "instrument_id": 269,
        "net_quantity": 100,
        "gross_realized_pnl": 0
      },
      {
        "trader_id": "c8170613-fd19-4e92-8cc9-f8f16dbedf4c",
        "instrument_id": 269,
        "net_quantity": -5,
        "gross_realized_pnl": 0
      },
      {
        "trader_id": "88103dea-2344-4d71-b251-64a264dd8e97",
        "instrument_id": 270,
        "net_quantity": 10,
        "gross_realized_pnl": -1000
      },
      {
        "trader_id": "c8170613-fd19-4e92-8cc9-f8f16dbedf4c",
        "instrument_id": 271,
        "net_quantity": 15,
        "gross_realized_pnl": 4900
      },
      {
        "trader_id": "88103dea-2344-4d71-b251-64a264dd8e97",
        "instrument_id": 271,
        "net_quantity": 15,
        "gross_realized_pnl": -1863
      },
      {
        "trader_id": "bba9ad2e-ab6d-4b71-9a68-6096d3fe699e",
        "instrument_id": 270,
        "net_quantity": 50,
        "gross_realized_pnl": -1600
      },
      {
        "trader_id": "c8170613-fd19-4e92-8cc9-f8f16dbedf4c",
        "instrument_id": 270,
        "net_quantity": -60,
        "gross_realized_pnl": 2450
      }
    ]
  },
  "cycles": [
    {
      "trader_ids": [
        "88103dea-2344-4d71-b251-64a264dd8e97",
        "bba9ad2e-ab6d-4b71-9a68-6096d3fe699e",
        "c8170613-fd19-4e92-8cc9-f8f16dbedf4c"
      ],
      "edge_counts": [
        6,
        4,
        3
      ]
    }
  ],
  "vectors": {
    "TGe5e744bd_0": {
      "id": 276,
      "instrument_id": 269,
      "captured_at": "2026-11-15T13:28:00+05:30",
      "features": [
        0.0,
        0.0,
        0.22529644,
        0.07,
        0.5,
        0.106749475
      ],
      "cosine_distance": 0.0
    },
    "TGe5e744bd_1": {
      "id": 280,
      "instrument_id": 270,
      "captured_at": "2026-11-15T13:28:00+05:30",
      "features": [
        0.0,
        0.0,
        -0.18204182,
        0.07,
        0.5,
        0.24106635
      ],
      "cosine_distance": 0.0
    },
    "TGe5e744bd_2": {
      "id": 282,
      "instrument_id": 271,
      "captured_at": "2026-11-15T13:28:00+05:30",
      "features": [
        0.0,
        0.0,
        -0.1,
        0.04,
        0.5,
        0.20456886
      ],
      "cosine_distance": 0.0
    }
  },
  "fts_result_id": 41,
  "rollup": [
    {
      "desk_id": 1,
      "realized_pnl": 2887,
      "execution_volume": 620
    },
    {
      "desk_id": 2,
      "realized_pnl": 2887,
      "execution_volume": 620
    }
  ],
  "optimizer": {
    "scenario": "price_band",
    "row_count": 1,
    "dataset_size": 18,
    "plans": {
      "forced_sequential": {
        "Plan": {
          "Node Type": "Aggregate",
          "Strategy": "Plain",
          "Partial Mode": "Simple",
          "Parallel Aware": false,
          "Async Capable": false,
          "Startup Cost": 2.27,
          "Total Cost": 2.27,
          "Plan Rows": 1,
          "Plan Width": 32,
          "Actual Startup Time": 0.013,
          "Actual Total Time": 0.013,
          "Actual Rows": 1,
          "Actual Loops": 1,
          "Shared Hit Blocks": 1,
          "Shared Read Blocks": 0,
          "Shared Dirtied Blocks": 0,
          "Shared Written Blocks": 0,
          "Local Hit Blocks": 0,
          "Local Read Blocks": 0,
          "Local Dirtied Blocks": 0,
          "Local Written Blocks": 0,
          "Temp Read Blocks": 0,
          "Temp Written Blocks": 0,
          "Plans": [
            {
              "Node Type": "Seq Scan",
              "Parent Relationship": "Outer",
              "Parallel Aware": false,
              "Async Capable": false,
              "Relation Name": "execution",
              "Alias": "execution",
              "Startup Cost": 0.0,
              "Total Cost": 2.26,
              "Plan Rows": 1,
              "Plan Width": 8,
              "Actual Startup Time": 0.005,
              "Actual Total Time": 0.006,
              "Actual Rows": 7,
              "Actual Loops": 1,
              "Filter": "((price_ticks >= '90'::smallint) AND (price_ticks <= '150'::smallint) AND (instrument_id = '269'::smallint))",
              "Rows Removed by Filter": 11,
              "Shared Hit Blocks": 1,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            }
          ]
        },
        "Planning": {
          "Shared Hit Blocks": 189,
          "Shared Read Blocks": 0,
          "Shared Dirtied Blocks": 0,
          "Shared Written Blocks": 0,
          "Local Hit Blocks": 0,
          "Local Read Blocks": 0,
          "Local Dirtied Blocks": 0,
          "Local Written Blocks": 0,
          "Temp Read Blocks": 0,
          "Temp Written Blocks": 0
        },
        "Planning Time": 0.332,
        "Triggers": [],
        "Execution Time": 0.036
      },
      "automatic": {
        "Plan": {
          "Node Type": "Aggregate",
          "Strategy": "Plain",
          "Partial Mode": "Simple",
          "Parallel Aware": false,
          "Async Capable": false,
          "Startup Cost": 2.27,
          "Total Cost": 2.27,
          "Plan Rows": 1,
          "Plan Width": 32,
          "Actual Startup Time": 0.009,
          "Actual Total Time": 0.01,
          "Actual Rows": 1,
          "Actual Loops": 1,
          "Shared Hit Blocks": 1,
          "Shared Read Blocks": 0,
          "Shared Dirtied Blocks": 0,
          "Shared Written Blocks": 0,
          "Local Hit Blocks": 0,
          "Local Read Blocks": 0,
          "Local Dirtied Blocks": 0,
          "Local Written Blocks": 0,
          "Temp Read Blocks": 0,
          "Temp Written Blocks": 0,
          "Plans": [
            {
              "Node Type": "Seq Scan",
              "Parent Relationship": "Outer",
              "Parallel Aware": false,
              "Async Capable": false,
              "Relation Name": "execution",
              "Alias": "execution",
              "Startup Cost": 0.0,
              "Total Cost": 2.26,
              "Plan Rows": 1,
              "Plan Width": 8,
              "Actual Startup Time": 0.004,
              "Actual Total Time": 0.005,
              "Actual Rows": 7,
              "Actual Loops": 1,
              "Filter": "((price_ticks >= '90'::smallint) AND (price_ticks <= '150'::smallint) AND (instrument_id = '269'::smallint))",
              "Rows Removed by Filter": 11,
              "Shared Hit Blocks": 1,
              "Shared Read Blocks": 0,
              "Shared Dirtied Blocks": 0,
              "Shared Written Blocks": 0,
              "Local Hit Blocks": 0,
              "Local Read Blocks": 0,
              "Local Dirtied Blocks": 0,
              "Local Written Blocks": 0,
              "Temp Read Blocks": 0,
              "Temp Written Blocks": 0
            }
          ]
        },
        "Planning": {
          "Shared Hit Blocks": 189,
          "Shared Read Blocks": 0,
          "Shared Dirtied Blocks": 0,
          "Shared Written Blocks": 0,
          "Local Hit Blocks": 0,
          "Local Read Blocks": 0,
          "Local Dirtied Blocks": 0,
          "Local Written Blocks": 0,
          "Temp Read Blocks": 0,
          "Temp Written Blocks": 0
        },
        "Planning Time": 0.296,
        "Triggers": [],
        "Execution Time": 0.028
      }
    }
  },
  "archive_count": 39,
  "race_accepted": 3,
  "race_rejected": 5,
  "negative_cases": {
    "bad_lot": 422,
    "inactive": 422,
    "insufficient": 409,
    "overflow": 422
  },
  "same_event_replay": "no-op",
  "conflicting_replay": "rejected",
  "request_key_replay": "409",
  "clean_restart_analytics": "rehydrated from committed executions",
  "scoped_cleanup": "complete",
  "existing_data_preserved": true
}
```

## Complete Batch B file manifest

Relative to the approved Batch A base; no frontend/schema/ER or original matcher file appears:

- `README.md`
- `backend/api/dependencies.py`
- `backend/api/main.py`
- `backend/api/routes/admin.py`
- `backend/api/routes/auth.py`
- `backend/api/routes/market.py`
- `backend/api/routes/orders.py`
- `backend/auth/rbac.py`
- `backend/auth/security.py`
- `backend/clearing/settlement.py`
- `backend/config.py`
- `backend/events/dispatcher.py`
- `backend/matching/engine.py`
- `backend/matching/fenwick.py`
- `backend/matching/rolling_vwap.py`
- `backend/risk/order_reservation.py`
- `backend/simulator/market_simulator.py`
- `backend/stores/neo4j_graph.py`
- `backend/stores/postgres.py`
- `backend/stores/redis_depth.py`
- `backend/stores/regimes.py`
- `backend/workers/cache_worker.py`
- `backend/workers/graph_worker.py`
- `backend/workers/regime_worker.py`
- `backend/workers/settlement_worker.py`
- `db/neo4j/constraints.cypher`
- `db/neo4j/retention.cypher`
- `db/neo4j/seed.cypher`
- `db/neo4j/wash_trade_cycles.cypher`
- `db/procedures/cancel_order.sql`
- `db/procedures/settle_execution.sql`
- `db/queries/full_text_search.sql`
- `db/queries/order_archive.sql`
- `db/queries/price_band_having.sql`
- `db/queries/query_indexes.sql`
- `db/queries/recursive_desk_rollup.sql`
- `db/queries/rolling_vwap.sql`
- `db/queries/set_operations.sql`
- `db/queries/vector_similarity.sql`
- `db/triggers/update_positions.sql`
- `db/views/order_book_view.sql`
- `docs/architecture/backend-contracts.md`
- `docs/architecture/backend-demo.md`
- `docs/architecture/backend-implementation-progress.md`
- `docs/architecture/normalization-proof.md`
- `docs/architecture/polyglot-data-models.md`
- `docs/architecture/query-optimization.md`
- `requirements.txt`
- `scripts/run_simulation.py`
- `scripts/setup_backend.sh`
- `tests/benchmarks/test_latency_isolation.py`
- `tests/benchmarks/test_matching_latency.py`
- `tests/concurrency/test_settlement_locks.py`
- `tests/integration/test_database_integrity.py`
- `tests/integration/test_order_pipeline.py`
- `tests/integration/test_polyglot.py`
- `tests/unit/test_fenwick.py`
- `tests/unit/test_order_book.py`
- `tests/unit/test_rolling_vwap.py`

A complete review diff is exported after the final commit to `/private/tmp/tradegraph-batch-b-review.diff`. The authoritative phase changes and messages are also in Git history.
