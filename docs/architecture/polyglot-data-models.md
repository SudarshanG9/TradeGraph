# Polyglot models and consistency

PostgreSQL is the single financial system of record. Its unchanged 13 tables
hold identity, instruments, cash/escrow, orders/history, executions, positions,
disclosures and regime snapshots. Redis and Neo4j are derived projections. No
ORM baseline, extra authoritative database, outbox or graph-event entity exists.

## Redis

`depth:{symbol}:bids` and `:asks` are ZSETs: score is price_ticks, member is its
canonical decimal string. Companion `:bids:qty` and `:asks:qty` hashes store exact
integer quantities as strings. Each side stores at most the best 20 levels.
`:meta` records owner epoch, zero-padded monotonic version and UTC freshness.
Bids read descending; asks ascending. Lua atomically reads/writes both side
structures. ZREM/HDEL remove drained/out-of-top-20 levels; DEL removes empty
side keys. Quantities never traverse Lua numeric JSON. Cache prices must be
1..2^53−1 because ZSET scores are doubles; the adapter rejects larger ticks
before reservation without altering BIGINT SQL schema. Individual/aggregate
quantities remain exact Python/hash integers.

One PG-leased owner emits ordered snapshots outside the matcher on submission,
fill and cancellation. Older versions in one epoch cannot overwrite newer ones.
A new owner may replace an old epoch only after the previous owner has closed
its workers/lease; startup refreshes known instruments. Read failures are 503,
uninitialized/aged data is marked stale, and canonical book snapshots rebuild
lost keys. No exchange state is read from Redis to decide money or matching.

## Neo4j

Only `(:Trader {id,name})` and directed
`[:EXECUTED_AGAINST {trade_count,total_notional,last_traded_at}]` exist. UUIDs
mirror PostgreSQL trader IDs; a unique constraint enforces identity. Notional
is integer minor currency units, with explicit signed-64-bit overflow rejection.
No `ProcessedExecution`, event node or additional relationship type is introduced.

After SQL commit, the consumer queries authoritative pair aggregates. MERGE
increments a newly missing canonical trade, while retries/backlogs/rebuilds
assign absolute counts/notional. `seed.cypher` accepts only aggregate facts
read from SQL. Rebuild removes orphan relationships only inside the known SQL
trader scope and never deletes unrelated graph IDs. A 90-day edge retention
query is scoped; fresh edges remain, canonical execution rows are untouched.
Simple-node cycles of length 3–5 are rotation-deduplicated, limited, and described
as surveillance candidates, not proof of misconduct. Admin-only API enforces JWT
role before graph access. SQL UUID/timestamp values are converted to strings at
the driver boundary; Cypher datetime() restores genuine temporal properties.
This avoids the observed native Python/Neo4j timezone-codec incompatibility.

## PostgreSQL vector and text

`regime_snapshot` retains `(instrument_id,captured_at)` uniqueness, VECTOR(6),
HNSW `vector_cosine_ops` and forced administrator RLS. These are engineered
microstructure features, not language-model embeddings. Feature order and units:

| Feature | Definition and normalization |
|---|---|
| spread | max(best ask ticks − best bid ticks,0)/100; clamp [0,1]; missing side=0 |
| order_book_imbalance | (total bid units − total ask units)/total; [−1,1]; empty=0 |
| vwap_drift | (last settled ticks − last-100-fill VWAP)/max(VWAP,1); clamp [−1,1]; missing=0 |
| trade_velocity | settled fill count over last 60 seconds /100; clamp [0,1] |
| depth_ratio | total bid units / total book units; [0,1]; empty=0.5 |
| realized_volatility | population stddev of consecutive tick returns over 60 seconds; clamp [0,1]; missing returns=0 |

Books are actual immutable coordinator snapshots, with all resting levels;
trades are committed SQL facts. VWAP numerator/volume is exact before conversion
to a nonfinancial feature. Retain UTC 60-second bucket timestamps: fill-driven
and admin on-demand capture UPSERT the current bucket. Per-instrument capture
locks/version checks reject older snapshots racing newer captures. No-observation
capture returns no snapshot. Query vectors must contain exactly six finite values
and have nonzero norm. Controlled axis vectors in tests are explicitly similarity
fixtures, not purported market observations.

Similarity orders by `features <=> query_vector LIMIT k`, optionally instrument
filtered, and returns distance, features, ID and timestamp. HNSW is approximate;
tiny tables may use sequential scans. No unmeasured acceleration is claimed.
Scoped explicit retention deletes snapshots older than a selected cutoff; the
demo uses 90 days and never prunes unrelated instruments automatically.

`market_disclosure.body_tsv` is the existing generated English tsvector with GIN.
Admin-context inserts create synthetic demo disclosures; websearch_to_tsquery and
ts_rank produce safely parameterized ranked search. Both tables require the
native compliance role AND SET LOCAL app.role=COMPLIANCE_ADMIN. Spoofing app.role
under trader_role cannot bypass grants. API TRADER tokens are rejected first.

## Ordering, failures and durability

Raw events pass to the single settlement worker. Only a committed execution
updates executed-volume Fenwick/VWAP, graph weights or regime vectors. Redis
also sees ordered resting-book changes. Every worker has a bounded queue;
derived jobs retain/retry their current payload on outages. Financial failure
or backlog overflow fails admissions closed. A derived outage can temporarily
make its projection stale without reversing committed cash. PostgreSQL canonical
facts permit graph/vector recovery; cache recovery requires a reconciled book.

The in-process queue is not durable. A process crash can lose a matched but
unsettled event. Startup refuses active unresolved orders; operators reconcile
SQL facts and independently retained immutable events, or explicitly cancel
residual reservations after diagnosis. No auto-rematching, unconditional event
loss prevention or production exactly-once delivery is claimed.
