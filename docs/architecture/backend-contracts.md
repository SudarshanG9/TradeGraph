# TradeGraph backend contracts — 1.0-review

Status: Phase 1 review candidate, 14 November 2026. Approval of this document is
required before Batch B. Only configuration and event types are implemented in
Phase 1; endpoints, dispatch, reservation installation and settlement remain later
phase work. The fee-collection schedule below is an explicit proposed clarification,
not existing financial behavior and not permission to execute Batch B.

## Authority and deployment

Sources read: the original `tradegraph-architecture-plan.md.pdf` (24 PDF pages,
page 24 blank; substantive content on pages 1–23) and the five-page
`DBMS Level 3 Project Requirements (1).pdf`, supplied from the user's Downloads.
The existing schema/ER, decisions and master plan were inspected. The user's
explicit native-only instruction overrides the source's Compose requirement:
native PostgreSQL with pgvector, Redis and Neo4j; no Docker file or command.
The original document's Git/Next.js deliverables do not authorize commits or UI
work in this batch. No architectural or datastore substitution is proposed.

Four tiers remain: future Next.js presentation; FastAPI authentication/risk;
pure Python single-writer matching/analytics; asynchronous settlement and derived
stores. PostgreSQL is authoritative for identities, instruments, orders, balances,
executions, positions, disclosures and regime snapshots. Redis holds derived
depth. Neo4j holds derived counterparty aggregates. pgvector remains inside
PostgreSQL, not a separate authoritative database.

## Frozen relational structure

Exactly these 13 production tables remain, without column/key/relationship changes:

| Table | Key / retained relationships |
|---|---|
| user_account | UUID id; unique email; TRADER or COMPLIANCE_ADMIN |
| desk | integer id; nullable self-parent and manager trader FKs |
| trader | UUID id; unique user_account FK; nullable desk FK |
| kyc_profile | trader_id identifying PK/FK |
| fee_tier | integer id; exact NUMERIC maker/taker basis points |
| margin_account | trader_id identifying PK/FK; fee_tier FK |
| instrument | integer id; unique symbol; positive tick_size and lot_size |
| order | BIGSERIAL id; trader/instrument FKs; existing statuses |
| order_history | original BIGINT id without sequence; trader/instrument FKs |
| execution | BIGSERIAL id; instrument and two trader FKs |
| position | composite (trader_id, instrument_id) PK/FKs |
| market_disclosure | BIGSERIAL id; optional instrument FK; generated body_tsv |
| regime_snapshot | BIGSERIAL id; instrument FK; unique instrument/time; VECTOR(6) |

There are 18 physical FKs. Execution order IDs intentionally have no FKs so
archival retains usable identifiers. The archive edge in the ER is logical.
Retain NOLOGIN `trader_role` and `compliance_admin_role`, both forced admin RLS
policies, GIN and HNSW cosine indexes, checks and current public matcher interfaces.
`TRADER_DESK_ASSIGNMENTS` and normalization counterexamples are hypothetical,
never extra production tables. No outbox, cost-basis column or fee ledger exists.
Differences between illustrative PDF DDL and the stronger live implementation
(explicit archive constraints, generated tsvector, restricted grants, forced RLS)
are preserved; the PDF is not an instruction to weaken working code.

## Units and validation

- price_ticks: positive integer tick count, at most 9223372036854775807.
- quantity: positive integer units, same maximum, divisible by instrument lot_size.
- instrument_id: positive PostgreSQL INTEGER, at most 2147483647.
- tick_size: minor currency units per tick; notional_minor = ticks × tick_size × units.
- cash, escrow, notional and realized PnL: integer minor currency units. Fees:
  exact NUMERIC basis points, 1 bp = 1/10000. Never binary floats for accounting.
- Use arbitrary-precision integers/exact Decimal or rational intermediates, then
  reject overflow before storing BIGINT. Reject booleans, fractional and coerced
  numeric strings at the API/event numeric boundary. Unknown JSON fields fail validation.
- Timestamps: timezone-aware UTC ISO-8601, serialized with Z. Trader IDs: canonical
  UUID strings on the wire. Book trader strings remain unchanged internally.
- Instrument tick/lot metadata and account fee-tier assignment/rates cannot mutate
  while relevant orders are OPEN/PARTIAL. Historical fee recomputation also requires
  retaining these bases after close: for this bounded academic build, freeze fee
  schedules, assignments and tick_size for the entire demo/replay history. A future
  mutable schedule needs an approved historical basis; no field is invented here.

## Matcher and event boundary

Existing frozen dataclasses and interfaces are unchanged:

```text
Order(order_id:int, trader_id:str, instrument_id:int, side:str,
      price_ticks:int, quantity:int)
Fill(instrument_id:int, buy_order_id:int, sell_order_id:int,
     buy_trader_id:str, sell_trader_id:str, price_ticks:int, quantity:int)
MatchResult(fills:tuple[Fill,...], remaining:int, resting:bool,
            self_trade_prevented:bool)
OrderBook.submit(Order) -> MatchResult
OrderBook.cancel(order_id) -> cancelled_remaining_quantity:int
OrderBook.depth(instrument_id, side) -> sorted list[(price_ticks, quantity)]
```

The book retains price-level heaps, doubly linked FIFO queues and order-ID index.
New price levels cost O(log P); direct known-node cancellation is expected O(1).
Depth scans/sorts and is a snapshot, not the API's fast Redis read path. Maker
price governs fills. A self-trade cancels the incoming residual only, preserving
earlier legitimate fills. The book never allocates DB IDs, timestamps or JWTs and
does no database, network, disk or asynchronous work.

Example committed order: Order(101, buyer UUID string, 1, BUY, 100, 100).
Example maker BUY 101 matched by incoming SELL 102: Fill(1, 101, 102,
buyer UUID string, seller UUID string, 100, 100).

`TradeEvent` is a frozen, slotted dataclass in backend/events/trade_event.py:

| Field | Python type | Meaning |
|---|---|---|
| event_id | int | preallocated execution.id, stable across retries |
| instrument_id | int | copied from existing Fill |
| buy_order_id / sell_order_id | int | distinct committed order IDs |
| buy_trader_id / sell_trader_id | UUID | distinct counterparties |
| price_ticks / quantity | int | positive exact fill values |
| taker_order_id | int | one of the two order IDs, supplied by coordinator |
| occurred_at | datetime | aware UTC event time, retained on every retry |

`TradeEvent.from_fill(fill, *, event_id, taker_order_id, occurred_at)` consumes
the existing Fill, not a duplicate fill type. `to_dict/from_dict` and
`to_json/from_json` round-trip this exact envelope:

```json
{"event_id":501,"instrument_id":1,"buy_order_id":101,"sell_order_id":102,
 "buy_trader_id":"00000000-0000-0000-0000-000000000001",
 "sell_trader_id":"00000000-0000-0000-0000-000000000002",
 "price_ticks":100,"quantity":100,"taker_order_id":102,
 "occurred_at":"2026-11-14T12:00:00Z"}
```

Only a committed reservation enters matching. One coordinator serializes the
whole admission sequence (reservation, commit, submission), not just submit calls;
one process and one Uvicorn worker. This establishes increasing order IDs in
admission order (sequence CACHE 1; no other order writer). Therefore the later
admitted/higher-ID order is taker. Future settlement must validate this invariant
and event taker identity. It makes maker/taker reconstructible from existing
execution order IDs even after archival; no taker column is added. If concurrent
admission or a different historical writer breaks this assumption, stop rather
than guess the historical fee role. Sequence gaps are harmless.

## Financial contract and proposed fee collection

The existing reservation routine reserves cash for BOTH BUY and SELL. Preserve
collateralized synthetic short selling: negative positions are possible; this is
not inventory custody or a production margin engine.

Let L = limit_ticks × tick_size, Q = original quantity, q = remaining quantity,
w = max(maker_bps,taker_bps)/10000, and F(q) = ceil(L×q×w).
Reserve R(q) = L×q + F(q), with R(0)=0. Each fill releases exactly
R(q_before) − R(q_after) from that order's escrow, never a newly rounded fee
reservation for the fill. Account escrow is pooled: derive each order's share
from its immutable order fields and fixed fee basis; never release the pool.

Naive CEIL per fill is unsafe. At L=100, Q=100, maker=1bp, taker=2bp,
the whole-order maximum fee reserve is 2. One big trade charges 1 maker + 2 taker;
100 one-unit trades naively charge 100 per side, exceeding the reserve. Even
cumulative CEIL(actual) can charge 1 on the first tiny fill while the reserve's
fee delta is zero. Splitting alone must not manufacture fees or negative cash.

**Proposal requiring Batch A approval: collect conservative BUY fee advances as
collateral is released; reconcile exact actual BUY fees at terminal processing.
SELL fees use cumulative exact assessment and are paid from sale proceeds.**
This makes the cash-collection schedule explicit instead of claiming immediate
per-fill actual fee debits can always fit each reserve delta.

For each BUY fill, fee advance = F(q_before) − F(q_after). Let V be executed
notional. Buyer cash credit = released reserve − V − advance. Buyer credit is
nonnegative because execution price cannot exceed its limit. These advances
are provisionally collected in the external fee sink,
not labelled assessed maker/taker fees.

Exact assessed fee for an order = ceil(sum(V_i × rate_i / 10000)), rounded ONCE
over all its executions. Rates depend on that order's maker/taker role per fill.
Use historical executions ordered by execution.id and order/history identifiers;
the actual rational fee accumulator is derived, not persisted in a new field.
For BUY at FILLED or CANCELLED, collect any remaining original fee budget as
part of releasing R(q), then refund F(Q) − assessed_fee in the SAME transaction.
For cancellation without fills the full BUY fee budget is refunded. For SELL,
each actual fee debit is ceil(cumulative exact fee after) minus ceil(cumulative
exact fee before); cash credit = released reserve + V − actual fee debit.
Cancel returns the entire remaining SELL R(q), since assessed fees were already
paid. Pending fills must settle before cancellation; no fee is collected twice.

Proof of BUY budget: each actual V_i×rate_i <= L×f_i×w, so assessed_fee <= F(Q)
for every partition, role mix and valid maker price. BUY advances telescope to
at most F(Q); terminal refund is nonnegative. SELL execution price may exceed
its limit, so its actual fee can exceed its collateral fee budget: never assume
the BUY bound for SELL. SELL fees are instead funded from proceeds. NUMERIC(6,3)
nonnegative rates are at most 999.999bp (<100%); each cumulative-ceiling fee
increment <= ceil(V_i×rate_i/10000) <= V_i. Thus SELL cash credit is nonnegative.
Total cash+escrow decreases by BUY advances plus assessed SELL fees during an
open BUY and by exact assessed fees once terminal. This qualifies the immediate per-fill
actual-fee description. If this schedule is rejected, settlement must wait for
an approved alternative; Phase 1 does not install either policy.

Worked ledger: both start cash=20000, escrow=0; both limit=100, Q=100,
tick_size=1; buyer is maker at 1bp, seller taker at 2bp; execute at 100.

| Point | Buyer cash | Buyer escrow | Seller cash | Seller escrow |
|---|---:|---:|---:|---:|
| Start | 20000 | 0 | 20000 | 0 |
| Reserve each R(100)=10002 | 9998 | 10002 | 9998 | 10002 |
| 50 units filled; BUY advance 1, SELL actual fee 1 | 9998 | 5001 | 19998 | 5001 |
| Cancel residual; assessed fee 1 each | 14999 | 0 | 24999 | 0 |
| Alternative: complete all 100; assessed 1/2 | 9999 | 0 | 29998 | 0 |

Full completion by one 100-unit fill or 100 one-unit fills gives the same last
row. After only one tiny fill, BUY advance is 0 and SELL actual fee is 1;
canceling charges BUY assessed fee 1 from the remaining BUY fee budget:
final buyer cash 19899, seller cash 20099, both escrow 0. No negative balance
or fee cap is used. A BUY limit 105 executing 50 at maker 100 releases 5251,
collects advance 1, spends 5000, and credits 250 price improvement.
Fees remain an external sink because the ER has no fee-revenue ledger.
For SELL limit 100 executed at a resting BUY 105 for all 100 units, the 2bp
SELL actual fee is 3 (larger than reserved fee 2), safely paid from proceeds
10500; final SELL cash is 30497 from starting cash 20000.

Gross realized PnL excludes fees. Future trigger recomputes each affected
position from executions in execution.id order using exact weighted-average
entry cost, long/short closing and zero-crossing rules. Persist net signed
quantity and round cumulative gross PnL to nearest minor unit, ties away from
zero, only at storage; recomputation retains exact rational intermediate cost.
Cost basis is not a fictional stored column. Complexity grows with history.

## Lifecycle, ordering and replay

OPEN -> PARTIAL -> FILLED; OPEN/PARTIAL -> CANCELLED. Filled quantity is
monotonic, never exceeds quantity. FILLED/CANCELLED may be archived only after
financial completion. API acceptance is reservation success, not settlement.
Cancel owns the same coordinator turn as submit, drains prior pending fills,
and performs terminal account processing once before archive. A fully FILLED
order cannot be canceled. Unknown/non-owned IDs do not disclose another trader.

Preallocate execution IDs from the existing sequence in orchestration, outside
the book, before a matching turn with capacity for its maximum fill count.
Keep an immutable event's ID/payload/time stable on retry. Settlement checks same
ID/same payload as a no-op; same ID/different payload is a conflict. Compare all
stored fields, validate taker via admission invariant, and use occurred_at for
executed_at. Lock accounts in ascending UUID order, then orders ascending ID,
using this order in every reservation/cancel/settlement interaction. Settlement
validates ownership, sides, limits/maker price, remaining capacity and fixed fee
basis, then execution, balances, order state and PnL commit atomically.

One bounded in-process queue and one settlement worker are proposed for the
academic demo, subject to this review. Reserve queue capacity/IDs BEFORE book
mutation. Worker acknowledges only after commit. Derived trade consumers and
in-memory executed-volume analytics see settled facts only. Redis additionally
receives ordered book snapshots for resting submissions/cancels; it does not
claim every resting order is a settled trade. Queue/worker failure makes health
unhealthy and rejects new trading; never silently drop a fill.

There is no durable outbox. A process crash can lose a matched-but-unsettled
event even though reservations survive. No exactly-once delivery or automatic
crash recovery is claimed. Stop admissions on restart; inspect orders, executions,
accounts and positions, replay only independently retained immutable events,
and reconcile/refund unsettled collateral under operator control. Rebuild Redis
and Neo4j from reconciled sources. Do not automatically rematch OPEN orders or
infer the missing original fill order from rows. If no retained event exists,
its original match cannot be proven/replayed. The source's unconditional
no-event-loss guarantee remains unmet without an approved durable mechanism.

## Identity, API and errors

JWT sub is user_account.id, role is TRADER/COMPLIANCE_ADMIN; iat/exp required,
HS256 configured explicitly, 15-minute default TTL. Server resolves trader.id
from subject, never request-supplied trader_id. No self-registration or UI.
POSTGRES_USER is legacy setup/owner configuration, never a runtime fallback.
The new runtime settings select POSTGRES_RUNTIME_USER (default tradegraph_runtime)
and POSTGRES_RUNTIME_PASSWORD independently. Phase 3 must provision/verify a
dedicated non-superuser LOGIN, without CREATEDB/CREATEROLE/BYPASSRLS, and narrow
routine grants; it is a service identity, not a third user-facing role. Phase 1
does not create this login. No direct runtime balance/order writes or arbitrary
SQL route. Controlled service code alone resolves/authenticates the trader passed
to SECURITY DEFINER routines. Configure effective PG role and SET LOCAL app.role
inside the same transaction; app.role alone never authenticates anyone.

All routes below are contracts for later phases, not implemented endpoints.
Responses use integer money/ticks/quantity, UUID strings and UTC timestamps.
Errors: {"error":{"code":"INSUFFICIENT_FUNDS","message":"..."}};
no SQL details, password/hash or credentials. 401 missing/invalid/expired token;
403 wrong role; 404 absent or non-owned resource; 422 invalid body/lot/instrument;
409 insufficient funds, terminal cancel or event conflict; 503 unhealthy trading.

| Method/path | Access | Request/query -> response fields |
|---|---|---|
| POST /login | public | email,password -> access_token,token_type=bearer,role,expires_in |
| GET /health | diagnostic | -> status, dependencies:{postgres,redis,neo4j}, trading_ready; dependency status/latency without credentials |
| POST /orders | TRADER | instrument_id,side,price_ticks,quantity -> order_id,status,accepted_at (201) |
| POST /orders/{id}/cancel | owner TRADER | -> order_id,status,cancelled_quantity (200) |
| GET /orders/me | TRADER | limit 1..100 (default 50), before_id -> items,next_before_id; each id/instrument/side/ticks/quantity/filled/status/times/archive flag |
| GET /account/me | TRADER | -> trader_id,cash_balance,escrow_balance,positions:[instrument_id,net_quantity,realized_pnl,pnl_basis=gross] |
| GET /market/{symbol}/book | authenticated | -> symbol,bids/asks:[price_ticks,quantity],as_of,stale; top 20 |
| GET /market/{symbol}/trades | authenticated | limit 1..100 default 50,before_id -> settled execution items,next_before_id |
| GET /market/{symbol}/analytics | authenticated | lower_ticks,upper_ticks -> vwap_ticks (decimal string or null),window_fills,band_volume,as_of |
| GET /admin/surveillance/cycles | admin | limit 1..100 default 25 -> candidates:[trader_ids,edge_counts]; lengths 3..5 |
| GET /admin/regimes/similar | admin | instrument_id,features (six finite values) or current=true; k 1..100 default 10 -> matches:[id,instrument_id,captured_at,features,cosine_distance] |
| GET /admin/disclosures/search | admin | q length 1..500,limit 1..100 default 20 -> items:[id,instrument_id,title,published_at,rank] |
| GET /admin/optimizer/compare | admin | scenario allowlist -> scenario,row_count,plans (actual EXPLAIN ANALYZE BUFFERS FORMAT JSON),dataset_size |
| GET /admin/desks/rollup | admin | -> items:[desk_id,realized_pnl,execution_volume]; recursive cycle guard |

Trade items include event/execution id, instrument, order/counterparty IDs,
price_ticks, quantity, executed_at from PostgreSQL, never synthetic settled data.
Decimal strings distinguish VWAP from cash; cosine distance and FTS rank are
nonfinancial floats. Query limits are bounded; all SQL values parameterized.
Future Pydantic/OpenAPI models must realize these contracts with strict integers.
Login credential failure is 401; authentication does not leak account existence.
Order status in the immediate accepted response is OPEN reservation status;
GET queries later reflect committed settlement. Service failure after reservation
is 503 with reconciliation required, not proof that the order never existed.

## Derived-store contracts

Redis: depth:{symbol}:bids/asks ZSET score=integer ticks, member=canonical ticks;
companion :qty HASH maps ticks to aggregate resting quantity. Bids descending,
asks ascending. Atomic updates/removal, delete empty sides. Monotonic coordinator
version prevents stale snapshots overwriting new ones. The adapter supports ticks
up to 2^53−1 exactly (documented demo bound); reject larger prices before risk
reservation when that adapter is enabled, without narrowing the SQL schema.
ZREM/HDEL/DEL implement eviction. Lost cache is rebuildable. The score change
corrects the PDF's quantity-score example, which cannot produce price order.

Neo4j: only (:Trader {id,name}) and directed EXECUTED_AGAINST with trade_count,
total_notional (minor units), last_traded_at. No processed-event node. MERGE
increments only distinct committed facts; reconcile absolute weights from
PostgreSQL on uncertain retries/restart. Ring lengths 3..5 are investigation
candidates, not findings of misconduct. Retention deletes derived edges only.

Vector feature order: [spread,order_book_imbalance,vwap_drift,trade_velocity,
depth_ratio,realized_volatility]. Each snapshot is six finite hand-engineered
normalized values, not a language-model embedding. Proposed demo interval=60s:
spread ticks/100 clamped [0,1]; imbalance=(bid_qty−ask_qty)/(bid_qty+ask_qty),
range [−1,1]; drift=(last_price−last-N VWAP)/max(VWAP,1), clamped [−1,1];
velocity=settled_fill_count_in_60s/100 clamped [0,1]; depth ratio=bid_qty/total_qty,
range [0,1]; volatility=population stddev of consecutive tick returns in 60s,
clamped [0,1]. Empty book features default 0, neutral depth ratio 0.5; missing
VWAP/returns defaults 0. Compute from real simulator observations, document
sample counts. No nonzero observation means no cosine-searchable snapshot
rather than a meaningless all-zero vector. Upsert by instrument/time, query
cosine HNSW with optional instrument filter; demo retention=90 days. Disclosures
use existing generated body_tsv/GIN and safe ranked queries. Both stay admin-only.

Fenwick tracks settled executed quantity once per event/instrument, not resting
depth. Bucket mapping/expansion is Phase 2 work. VWAP is a true cumulative-prefix
ring over last N fills (default N=100), exact integer sums with decimal string
presentation; distinct from SQL's rolling ten-minute time window.

## Native operations and safe installation order

Keep existing .env and databases. Existing scripts use POSTGRES_ADMIN_HOST
(default /tmp), POSTGRES_ADMIN_USER (default OS user), POSTGRES_PORT=5432 and
POSTGRES_DB=tradegraph; libpq .pgpass handles an admin password. These remain
separate from runtime settings. Native data directories remain managed by the
user's PostgreSQL/Redis/Neo4j installations. Do not copy .env.example over .env.
No schema/bootstrap/seeding, service reset, credential reset or volume deletion
is part of Phase 1. Already running services need no setup repetition.

Reproduce verification from the project root, using the existing venv:

```bash
source .venv/bin/activate
python scripts/verify_schema.py
python -m pytest tests/unit/test_matching_engine.py tests/unit/test_matching.py -q
python -m pytest -m day1 -q
redis-cli -h 127.0.0.1 -p 6379 PING
# Use cypher-shell with NEO4J_USERNAME/NEO4J_PASSWORD supplied securely from .env:
# RETURN 1 AS healthy;
```

Native PostgreSQL's verifier checks its socket connection and extensions; Redis
PING must return PONG; authenticated Neo4j RETURN 1 must return 1. Process/port
availability alone is not application health. Health timeout defaults 3s,
poll interval 10s; queue capacity 1024; one service worker. Runtime settings load
the root .env lazily with process environment precedence and redact secret fields
from repr. Importing configuration does not connect or load global credentials.
Placeholder/missing credentials fail validation when Settings.from_env is called.
That failure does not require overwriting the user's working admin .env in Phase 1.

Future install order (NOT executed in this batch):
1. Verify the existing schema and preserve all user rows. Fresh databases alone
   use setup_day1.sh; never rerun bootstrap on this initialized database.
2. Phase 2: create incremental scripts/setup_backend.sh, verify compatible catalog
   signatures, transactionally install place_and_reserve_order.sql once. Its
   current CREATE FUNCTION is not rerunnable without an explicit catalog guard.
3. Phase 3: provision/verify the runtime service login and narrowly scoped grants;
   validate server-side JWT identity and effective DB roles. No admin fallback.
4. Phase 4, only after accounting approval: install position recomputation and
   trigger dependency, settlement, then approved cancellation routine; preserve
   identity/retry semantics and fixed bases. Run real financial/concurrency tests.
5. Later phases install compatible view/queries/indexes and derived-store
   constraints in source order. No new migration baseline or production table.

Remaining course requirements, including full advanced SQL, NoSQL/vector
operations, benchmarks, simulator and Next.js demonstration, are not completed
by a Phase 1 contract. Batch B and the frontend remain separately authorized work.
