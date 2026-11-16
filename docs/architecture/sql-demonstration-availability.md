# SQL demonstrations and availability

PostgreSQL remains financial truth; one Python matching owner holds an advisory
lock. SERVICE_WORKERS stays 1. Health keeps existing fields and adds owner lock,
replay progress, financial worker, derived readiness, closing and reconciliation
flags. PostgreSQL connectivity alone does not establish trading readiness.

| SQL asset | Reachability | Verification |
| --- | --- | --- |
| price_band_having.sql | Tested demonstration via internal Database.named('bands'); no public endpoint | GROUP BY/HAVING execution volume |
| rolling_vwap.sql | Tested internal named query; live market analytics uses the separate last-100-fill Python ring | SQL ten-minute RANGE window and old-fill exclusion |
| set_operations.sql | Tested internal maker_taker/nested_range/correlated_orders; no arbitrary SQL API | INTERSECT/EXCEPT/UNION and both/maker-only classification; nested/correlated predicates |
| recursive_desk_rollup.sql | Live authorized GET /admin/desks/rollup | Recursive subtree, exact gross PnL and trader-leg volume |
| full_text_search.sql | Live authorized GET /admin/disclosures/search | GIN-compatible text search and authorization |
| vector_similarity.sql | Live authorized GET /admin/regimes/similar | VECTOR(6), cosine similarity, scoped optional retention |
| order_archive.sql | Internal bounded maintenance function/worker; opt-in schedule | Atomic move, terminal/reconciled eligibility, rollback, concurrent locking |
| query_indexes.sql | Installation/deployment DDL; no HTTP execution | Native query plans and additive CONCURRENTLY migration evidence |

All named reads use explicit transaction-scoped compliance context. There is no
public generic-query endpoint. Market depth uses the real in-memory book and Redis;
SQL order_book_view remains a tested persisted-state demonstration. The SQL VWAP
window and Python fill-count window intentionally differ.

For planned maintenance, stop the simulator through its authorized cleanup path,
stop new admissions and drain the financial worker before releasing ownership.
Housekeeping runs off-loop and shutdown waits for its database work. Do not kill
an owner or auto-cancel human orders for availability. Run the read-only restart
diagnostic before a cold start. Active-order restart still requires operator
reconciliation of FIFO, reservations, remaining quantities and outstanding matches.
Do not change SERVICE_WORKERS to multiple owners. Active-active HA requires an
approved ownership/replicated-book/durable-event redesign and remains unimplemented.

Deploy additive migrations separately after review; never run the full installer
against live trading. Configure shared frontend Redis sessions and encryption key,
validated production HTTPS APP_ORIGIN, and maintenance policy before enabling them.
Existing processes are not redeployed by a source commit. A healthy single owner
and bounded replay improve recovery without claiming multi-process matching HA.
