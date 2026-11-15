# Query optimization evidence — Phase 5

Native PostgreSQL 17.12, 4,000 real settled fills across 40 synthetic pairs,
100 one-unit fills per pair, executed at increasing timestamps. Every fill used
the actual reservation and settlement functions and position trigger. The lab
ran in one transaction and rolled back all synthetic rows. This is a bounded
academic dataset, not a production latency or scalability claim. Existing data
was preserved. Seed and query measurements are separate.

Indexes: existing B-tree on instrument/time; compatible new BRIN on time
(pages_per_range=4) and covering B-tree on (instrument,price) INCLUDE
(quantity,executed_at). No planner setting changed outside the lab transaction;
forced modes used savepoints and were rolled back. The automatic planner choice
is reported honestly. Newly inserted, unvacuumed data requires heap visibility
checks even when a covering/index-only plan is available. BRIN is a teaching
comparison on time-correlated rows, not an asserted universal improvement.

Reproduce (native services, existing .venv):

```bash
TRADEGRAPH_PLAN_REPORT=/private/tmp/tradegraph-plans.json PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/integration/test_database_integrity.py::test_optimizer_real_execution_lab -q
```

The admin optimizer API is role protected, uses allowlisted parameterized scenarios,
read-only transactions, real EXPLAIN ANALYZE/BUFFERS/JSON, and separately labels
forced sequential and automatic plans. It uses live data rather than lab fixtures.
Fenwick and prefix-ring comparisons and matching latency distributions are Phase 10.

| Mode | Execution ms | Plan |
|---|---:|---|
| forced_sequential | 0.226 | Aggregate → Seq Scan |
| automatic_covering | 0.032 | Aggregate → Bitmap Heap Scan → Bitmap Index Scan idx_execution_price_cover |
| automatic_btree | 0.013 | Bitmap Heap Scan → Bitmap Index Scan idx_execution_instrument_time |
| automatic_time | 0.273 | Aggregate → Bitmap Heap Scan → Bitmap Index Scan idx_execution_time_brin |
| forced_brin_teaching | 0.257 | Aggregate → Bitmap Heap Scan → Bitmap Index Scan idx_execution_time_brin |

Full measured JSON (no synthetic EXPLAIN output):

```json
{
  "rows": 4000,
  "seed_seconds": 6.313888375007082,
  "plans": {
    "forced_sequential": {
      "Plan": {
        "Node Type": "Aggregate",
        "Strategy": "Plain",
        "Partial Mode": "Simple",
        "Parallel Aware": false,
        "Async Capable": false,
        "Startup Cost": 118.25,
        "Total Cost": 118.26,
        "Plan Rows": 1,
        "Plan Width": 32,
        "Actual Startup Time": 0.221,
        "Actual Total Time": 0.221,
        "Actual Rows": 1,
        "Actual Loops": 1,
        "Shared Hit Blocks": 58,
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
            "Total Cost": 118.0,
            "Plan Rows": 100,
            "Plan Width": 8,
            "Actual Startup Time": 0.11,
            "Actual Total Time": 0.216,
            "Actual Rows": 100,
            "Actual Loops": 1,
            "Filter": "((instrument_id = '1'::smallint) AND (price_ticks = 1020))",
            "Rows Removed by Filter": 3900,
            "Shared Hit Blocks": 58,
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
        "Shared Hit Blocks": 71,
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
      "Planning Time": 0.305,
      "Triggers": [],
      "Execution Time": 0.226
    },
    "automatic_covering": {
      "Plan": {
        "Node Type": "Aggregate",
        "Strategy": "Plain",
        "Partial Mode": "Simple",
        "Parallel Aware": false,
        "Async Capable": false,
        "Startup Cost": 70.74,
        "Total Cost": 70.75,
        "Plan Rows": 1,
        "Plan Width": 32,
        "Actual Startup Time": 0.027,
        "Actual Total Time": 0.027,
        "Actual Rows": 1,
        "Actual Loops": 1,
        "Shared Hit Blocks": 10,
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
            "Node Type": "Bitmap Heap Scan",
            "Parent Relationship": "Outer",
            "Parallel Aware": false,
            "Async Capable": false,
            "Relation Name": "execution",
            "Alias": "execution",
            "Startup Cost": 9.3,
            "Total Cost": 70.49,
            "Plan Rows": 100,
            "Plan Width": 8,
            "Actual Startup Time": 0.017,
            "Actual Total Time": 0.021,
            "Actual Rows": 100,
            "Actual Loops": 1,
            "Recheck Cond": "((instrument_id = '1'::smallint) AND (price_ticks = 1020))",
            "Rows Removed by Index Recheck": 0,
            "Exact Heap Blocks": 2,
            "Lossy Heap Blocks": 0,
            "Shared Hit Blocks": 10,
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
                "Node Type": "Bitmap Index Scan",
                "Parent Relationship": "Outer",
                "Parallel Aware": false,
                "Async Capable": false,
                "Index Name": "idx_execution_price_cover",
                "Startup Cost": 0.0,
                "Total Cost": 9.28,
                "Plan Rows": 100,
                "Plan Width": 0,
                "Actual Startup Time": 0.014,
                "Actual Total Time": 0.014,
                "Actual Rows": 100,
                "Actual Loops": 1,
                "Index Cond": "((instrument_id = '1'::smallint) AND (price_ticks = 1020))",
                "Shared Hit Blocks": 8,
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
          }
        ]
      },
      "Planning": {
        "Shared Hit Blocks": 0,
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
      "Planning Time": 0.021,
      "Triggers": [],
      "Execution Time": 0.032
    },
    "automatic_btree": {
      "Plan": {
        "Node Type": "Bitmap Heap Scan",
        "Parallel Aware": false,
        "Async Capable": false,
        "Relation Name": "execution",
        "Alias": "execution",
        "Startup Cost": 4.8,
        "Total Cost": 64.48,
        "Plan Rows": 51,
        "Plan Width": 8,
        "Actual Startup Time": 0.006,
        "Actual Total Time": 0.009,
        "Actual Rows": 51,
        "Actual Loops": 1,
        "Recheck Cond": "((instrument_id = '1'::smallint) AND (executed_at >= '2026-11-15 11:56:21.132029+05:30'::timestamp with time zone))",
        "Rows Removed by Index Recheck": 0,
        "Exact Heap Blocks": 3,
        "Lossy Heap Blocks": 0,
        "Shared Hit Blocks": 5,
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
            "Node Type": "Bitmap Index Scan",
            "Parent Relationship": "Outer",
            "Parallel Aware": false,
            "Async Capable": false,
            "Index Name": "idx_execution_instrument_time",
            "Startup Cost": 0.0,
            "Total Cost": 4.79,
            "Plan Rows": 51,
            "Plan Width": 0,
            "Actual Startup Time": 0.004,
            "Actual Total Time": 0.004,
            "Actual Rows": 52,
            "Actual Loops": 1,
            "Index Cond": "((instrument_id = '1'::smallint) AND (executed_at >= '2026-11-15 11:56:21.132029+05:30'::timestamp with time zone))",
            "Shared Hit Blocks": 2,
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
        "Shared Hit Blocks": 13,
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
      "Planning Time": 0.028,
      "Triggers": [],
      "Execution Time": 0.013
    },
    "automatic_time": {
      "Plan": {
        "Node Type": "Aggregate",
        "Strategy": "Plain",
        "Partial Mode": "Simple",
        "Parallel Aware": false,
        "Async Capable": false,
        "Startup Cost": 73.48,
        "Total Cost": 73.49,
        "Plan Rows": 1,
        "Plan Width": 8,
        "Actual Startup Time": 0.268,
        "Actual Total Time": 0.269,
        "Actual Rows": 1,
        "Actual Loops": 1,
        "Shared Hit Blocks": 63,
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
            "Node Type": "Bitmap Heap Scan",
            "Parent Relationship": "Outer",
            "Parallel Aware": false,
            "Async Capable": false,
            "Relation Name": "execution",
            "Alias": "execution",
            "Startup Cost": 12.01,
            "Total Cost": 73.35,
            "Plan Rows": 51,
            "Plan Width": 0,
            "Actual Startup Time": 0.26,
            "Actual Total Time": 0.264,
            "Actual Rows": 51,
            "Actual Loops": 1,
            "Recheck Cond": "(executed_at >= '2026-11-15 11:56:21.132029+05:30'::timestamp with time zone)",
            "Rows Removed by Index Recheck": 3949,
            "Exact Heap Blocks": 0,
            "Lossy Heap Blocks": 58,
            "Shared Hit Blocks": 63,
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
                "Node Type": "Bitmap Index Scan",
                "Parent Relationship": "Outer",
                "Parallel Aware": false,
                "Async Capable": false,
                "Index Name": "idx_execution_time_brin",
                "Startup Cost": 0.0,
                "Total Cost": 12.0,
                "Plan Rows": 267,
                "Plan Width": 0,
                "Actual Startup Time": 0.008,
                "Actual Total Time": 0.008,
                "Actual Rows": 580,
                "Actual Loops": 1,
                "Index Cond": "(executed_at >= '2026-11-15 11:56:21.132029+05:30'::timestamp with time zone)",
                "Shared Hit Blocks": 5,
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
          }
        ]
      },
      "Planning": {
        "Shared Hit Blocks": 4,
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
      "Planning Time": 0.02,
      "Triggers": [],
      "Execution Time": 0.273
    },
    "forced_brin_teaching": {
      "Plan": {
        "Node Type": "Aggregate",
        "Strategy": "Plain",
        "Partial Mode": "Simple",
        "Parallel Aware": false,
        "Async Capable": false,
        "Startup Cost": 73.48,
        "Total Cost": 73.49,
        "Plan Rows": 1,
        "Plan Width": 8,
        "Actual Startup Time": 0.253,
        "Actual Total Time": 0.253,
        "Actual Rows": 1,
        "Actual Loops": 1,
        "Shared Hit Blocks": 60,
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
            "Node Type": "Bitmap Heap Scan",
            "Parent Relationship": "Outer",
            "Parallel Aware": false,
            "Async Capable": false,
            "Relation Name": "execution",
            "Alias": "execution",
            "Startup Cost": 12.01,
            "Total Cost": 73.35,
            "Plan Rows": 51,
            "Plan Width": 0,
            "Actual Startup Time": 0.247,
            "Actual Total Time": 0.251,
            "Actual Rows": 51,
            "Actual Loops": 1,
            "Recheck Cond": "(executed_at >= '2026-11-15 11:56:21.132029+05:30'::timestamp with time zone)",
            "Rows Removed by Index Recheck": 3949,
            "Exact Heap Blocks": 0,
            "Lossy Heap Blocks": 58,
            "Shared Hit Blocks": 60,
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
                "Node Type": "Bitmap Index Scan",
                "Parent Relationship": "Outer",
                "Parallel Aware": false,
                "Async Capable": false,
                "Index Name": "idx_execution_time_brin",
                "Startup Cost": 0.0,
                "Total Cost": 12.0,
                "Plan Rows": 267,
                "Plan Width": 0,
                "Actual Startup Time": 0.003,
                "Actual Total Time": 0.003,
                "Actual Rows": 580,
                "Actual Loops": 1,
                "Index Cond": "(executed_at >= '2026-11-15 11:56:21.132029+05:30'::timestamp with time zone)",
                "Shared Hit Blocks": 2,
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
          }
        ]
      },
      "Planning": {
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
      },
      "Planning Time": 0.015,
      "Triggers": [],
      "Execution Time": 0.257
    }
  },
  "note": "Uncommitted real settled rows; visibility map not vacuumed. Forced plans are labelled; no forced speedup claim."
}
```
