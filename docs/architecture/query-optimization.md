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

## Phase 10 measured core and latency isolation

Hardware: Apple M1; macOS-26.5.2-arm64-arm-64bit-Mach-O; 8 logical CPUs. Python 3.13.0 (v3.13.0:60403a5409f, Oct  7 2024, 00:37:40) [Clang 15.0.0 (clang-1500.3.9.4)]. Warmup: 200 calls per pure operation. Orders are prebuilt; core timers exclude network/database work.

| Operation (microseconds) | Samples | Median | p95 | p99 |
|---|---:|---:|---:|---:|
| submit_existing_level_us | 5000 | 1.958 | 2.291 | 2.625 |
| submit_new_level_us | 5000 | 2.084 | 2.375 | 3.625 |
| known_node_cancel_us | 5000 | 0.333 | 0.375 | 0.375 |
| one_fill_match_us | 5000 | 2.250 | 2.333 | 2.334 |
| depth_1024_levels_us | 2000 | 96.770 | 105.250 | 159.125 |
| fenwick_point_add_us | 5000 | 1.291 | 1.541 | 1.625 |
| fenwick_range_65536_us | 2000 | 0.875 | 0.917 | 0.959 |
| direct_scan_range_65536_us | 2000 | 291.125 | 293.459 | 299.000 |
| prefix_ring_add_us | 5000 | 0.333 | 0.375 | 0.458 |
| prefix_ring_vwap_4096_us | 2000 | 0.917 | 0.959 | 1.000 |
| rescan_vwap_4096_us | 2000 | 286.292 | 288.291 | 294.958 |

Fenwick uses 65,536 stable coordinates; dynamic expansion costs O(M log M) and
was not included in the steady-state timing. Prefix-ring comparison uses N=4096
and actual cumulative-prefix subtraction, compared with an independent history
rescan. Depth snapshots scan/sort 1024 levels and are not the matching hot path.

A real Neo4j reconciliation worker was gated: 2,000 fills completed while the
worker remained blocked, before release. Both baseline and gated core distributions
are reported; shared scheduling can vary. Separate native ASGI tests measure 20
API order pairs/settlements per case, plus 40 isolated submit calls per case,
with an injected 50ms graph-consumer delay. They include actual PG financial
transactions and actual graph writes; ASGI transport excludes external TCP/client
latency. These samples have no artificial latency pass threshold, and they do not
prove statistically identical distributions, production scalability or a guaranteed
microsecond SLA. Core structural nondependency is tested with an explicit gate.

Reproduce:

```bash
TRADEGRAPH_BENCHMARK_REPORT=/private/tmp/tradegraph-core.json TRADEGRAPH_ISOLATION_REPORT=/private/tmp/tradegraph-isolation.json PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest tests/benchmarks -q
```

Full measured latency evidence:

```json
{
  "gated_graph": {
    "baseline_core_us": {
      "samples": 2000,
      "median": 2.625,
      "p95": 2.709,
      "p99": 2.792
    },
    "gated_core_us": {
      "samples": 2000,
      "median": 2.833,
      "p95": 2.917,
      "p99": 3.042
    },
    "downstream_completion_ms": 74.19725,
    "core_completed_while_graph_gated": true,
    "interpretation": "Structural independence proven; distributions may vary due to shared CPU scheduling."
  },
  "native_api": {
    "baseline": {
      "core_us": {
        "samples": 40,
        "median": 13.8335,
        "p95": 32.75,
        "p99": 74.708
      },
      "settlement_transaction_ms": {
        "samples": 20,
        "median": 6.201021000000001,
        "p95": 12.04475,
        "p99": 17.070625
      },
      "api_pair_to_settled_ms": {
        "samples": 20,
        "median": 28.862145499999997,
        "p95": 45.101917,
        "p99": 80.656625
      },
      "shutdown_derived_drain_ms": 15.21425,
      "injected_graph_delay_ms": 0
    },
    "slow_graph": {
      "core_us": {
        "samples": 40,
        "median": 14.000499999999999,
        "p95": 32.042,
        "p99": 34.667
      },
      "settlement_transaction_ms": {
        "samples": 20,
        "median": 6.3795835,
        "p95": 8.560375,
        "p99": 9.367167
      },
      "api_pair_to_settled_ms": {
        "samples": 20,
        "median": 28.0231875,
        "p95": 33.89375,
        "p99": 50.29975
      },
      "shutdown_derived_drain_ms": 994.287542,
      "injected_graph_delay_ms": 50
    },
    "transport": "in-process ASGI HTTP plus real native services; excludes external TCP/client latency"
  }
}
```
