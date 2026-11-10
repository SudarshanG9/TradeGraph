# TradeGraph

A simulated electronic exchange designed to match orders, settle trades, and monitor its own trading activity for signs of market manipulation.

> **Project status.** Day 1 includes the local database stack, schema, synthetic seed data, and database integration tests. The application tiers and performance targets below describe the intended design.

## Table of Contents

1. [Problem Statement](#problem-statement)
2. [What TradeGraph Does](#what-tradegraph-does)
3. [Project Overview](#project-overview)
4. [System-Level Design](#system-level-design)
5. [Database-Level Design](#database-level-design)
6. [Schema](#schema)
7. [System Architecture](#system-architecture)
8. [System Flow](#system-flow)
9. [Optimizations](#optimizations)
10. [Future Work](#future-work)
11. [Tech Stack](#tech-stack)
12. [Getting Started](#getting-started)

## Problem Statement

An exchange has to satisfy two competing requirements: fast matching and correct financial state.

**Matching must be fast.** Incoming orders are compared against resting orders under strict price-time priority, with a target of microsecond-level execution. A delay on this path affects every participant.

**Everything around matching must be correct.** Before accepting an order, the system must verify that the trader can afford it. After a trade, money must move atomically between accounts. Records must remain consistent under concurrent activity, and suspicious trading patterns must be detectable afterward. A lost update or double-spent balance is a correctness failure.

A design focused only on speed can omit necessary safety checks. A design that serializes every operation through a single database can make matching too slow.

TradeGraph separates these concerns into distinct tiers. Each tier uses the storage and execution model suited to its responsibility, with the goal of keeping settlement and surveillance work off the matching path.

## What TradeGraph Does

TradeGraph is designed to expose two roles with different views of the system.

### Trader

- Place buy and sell orders on listed instruments.
- Watch orders match against the live order book.
- View balances, positions, and realized profit and loss as trades settle.

### Compliance / Admin

- Access surveillance tooling restricted from traders.
- Detect closed trading rings, such as A trading with B, B with C, and C with A, as potential wash-trading patterns.
- Search historical market conditions for periods statistically similar to the present.
- Search market disclosures using full-text queries.

Every order is intended to pass a risk check before acceptance, and every trade is intended to settle inside a database transaction. Order-book depth, the trading graph, and market-regime similarity data update asynchronously.

## Project Overview

| Tier | Responsibility | Technology |
| --- | --- | --- |
| 1. Presentation | Trading terminal, query and optimizer lab, surveillance console | Next.js |
| 2. Pre-trade risk and access control | Authentication, role enforcement, balance verification, fund escrow | FastAPI, PostgreSQL |
| 3. Matching | Price-time priority matching and in-memory analytics | Standalone in-memory Python engine |
| 4. Settlement and surveillance | Durable settlement, live depth cache, trade graph, similarity search | PostgreSQL, Redis, Neo4j, pgvector |

Tier 2 is the only synchronous gate before matching. Tier 3 performs no database or network calls. Tier 4 consumes events asynchronously and has no synchronous dependency back into Tier 3. The design aims to keep matching latency independent of downstream query and settlement load.

### Repository Layout

```text
TradeGraph/
├── frontend/                  # Next.js presentation layer
│   ├── src/
│   │   ├── app/               # Login, trade, optimizer, surveillance pages
│   │   ├── components/        # Trading, optimizer, surveillance, common UI
│   │   ├── hooks/
│   │   ├── lib/
│   │   └── types/
│   └── public/
├── backend/
│   ├── config.py
│   ├── api/                   # FastAPI gateway, dependencies, routes
│   ├── auth/                  # Security and role-based access control
│   ├── risk/                  # Pre-trade order reservation
│   ├── matching/              # Isolated matching engine and analytics
│   ├── events/                # Trade events and dispatch
│   ├── clearing/              # Settlement
│   ├── stores/                # PostgreSQL, Redis, Neo4j, regime adapters
│   ├── workers/               # Asynchronous downstream consumers
│   └── simulator/             # Market simulator
├── db/
│   ├── schema.sql             # Planned PostgreSQL schema: 13 tables
│   ├── seed.sql
│   ├── procedures/            # Order reservation and settlement
│   ├── triggers/              # Position maintenance
│   ├── views/                 # Order-book view
│   ├── queries/               # Archive, rollup, analytics, search examples
│   └── neo4j/                 # Constraints, seed, cycle detection, retention
├── tests/
│   ├── unit/
│   ├── concurrency/
│   ├── integration/
│   └── benchmarks/
├── scripts/                   # Schema verification, demo seed, simulation
├── docs/                      # ER, architecture, normalization, data models,
│                              # query plans, demo, report
├── .env
├── .env.example
├── .gitignore
├── requirements.txt
├── pytest.ini
└── README.md
```

## System-Level Design

This section describes the intended Tier 3 matching engine.

### Order Book

A hash map maps prices to linked lists of resting orders. A secondary index maps order IDs to list nodes. At an identified price level, insertion, accessing the oldest resting order, and removing an indexed order are designed to be O(1). Finding the best price across levels requires separate price-level management.

### Fixed-Point Pricing

Prices and quantities use integers: prices in ticks and quantities in lots. The money path avoids floating-point arithmetic to prevent rounding drift.

### Rolling VWAP

A prefix-sum ring buffer maintains cumulative price-volume and volume totals over a fixed window. A volume-weighted average price query uses two differences and a division, independent of window size.

### Price-Band Volume

A Fenwick tree over price buckets supports total traded volume between two prices in O(log M), with O(log M) updates, where M is the number of price buckets.

### Single-Writer Execution

One thread owns the book. The matching path has no locks, database calls, or network calls. Each fill emits an immutable `TradeEvent`; the engine continues without waiting for downstream consumers.

### Verification

The planned verification compares the engine against a deliberately simple brute-force reference matcher over large randomized order sequences. Both implementations must produce identical fills.

## Database-Level Design

This section describes the intended guarantees for Tiers 2 and 4.

### Transactional Guarantees

**Pre-trade risk gate:** `place_and_reserve_order()` executes as a single transaction:

1. Lock the trader's `margin_account` row using `SELECT ... FOR UPDATE`.
2. Verify that the available balance covers the order.
3. Move funds into escrow.
4. Insert the order with status `OPEN`.
5. Commit.

The row lock serializes concurrent orders against the same account, preventing two orders from drawing on a balance that covers only one.

**Settlement:** `settle_execution()` moves funds atomically between counterparties. Both account rows are locked in ascending trader ID order to prevent circular waits between these account locks. An `AFTER INSERT` trigger on `execution` updates positions and realized P&L within the same transaction.

### Polyglot Persistence

PostgreSQL is the system of record. Other stores contain derived data for specific access patterns.

| Store | Access pattern | Reason for selection |
| --- | --- | --- |
| PostgreSQL | Transactional state, relational integrity, full-text search | ACID transactions, constraints, joins, `tsvector` and GIN indexes |
| Redis | Top-20 order-book depth per instrument; low-latency reads | Sorted sets support ordered access, with O(log n) updates and O(log n + k) range reads |
| Neo4j | Counterparty relationships and cycle detection | Variable-length paths express closed trading rings |
| pgvector | Nearest-neighbor search over market-behavior vectors | HNSW with cosine distance and relational filters in the same query |

### Access Control

The application validates a role-scoped JWT on each request. Independently, the gateway sets `app.role` within database transactions, while PostgreSQL roles and row-level security restrict compliance-only data in `market_disclosure` and `regime_snapshot`.

## Schema

The DDL lives in [`db/schema.sql`](db/schema.sql) and defines 13 tables, two database roles, row-level security policies, and indexes. The [ER diagram](docs/er/tradegraph-er.md) and [Day 1 architecture decisions](docs/architecture/day1-decisions.md) describe the relationships and constraints.

| Table | Purpose |
| --- | --- |
| `user_account` | Credentials stored as bcrypt hashes and user role |
| `trader` | Trading identity, one-to-one with `user_account` |
| `kyc_profile` | Identity verification record; weak entity of `trader` |
| `desk` | Self-referencing desk hierarchy through `parent_desk_id` |
| `fee_tier` | Maker and taker fee schedule |
| `margin_account` | Cash and escrow balances; weak entity of `trader` |
| `instrument` | Tradable instruments, tick sizes, and lot sizes |
| `order` | Open orders |
| `order_history` | Archive of cancelled and filled orders |
| `execution` | Completed trades |
| `position` | Net quantity and realized P&L per trader and instrument |
| `market_disclosure` | Full-text-searchable disclosures; compliance only |
| `regime_snapshot` | Six-dimensional market-behavior vectors; compliance only |

Database integrity is intended to rely on `CHECK` constraints for sides, statuses, and non-negative balances; foreign keys across relationships; `UNIQUE` constraints on identifiers; and a constraint preventing self-trades.

### Non-Relational Models

**Redis depth keys**

| Key | Type | Planned content |
| --- | --- | --- |
| `depth:{symbol}:bids` | Sorted set | Price in ticks as member; aggregate resting quantity as score |
| `depth:{symbol}:asks` | Sorted set | Same representation for the ask side |

The score determines Redis sorted-set ordering; price-ordered top-20 retrieval must account for this when implementing the depth adapter.

**Neo4j counterparty graph**

```text
(:Trader {id, name})
  -[:EXECUTED_AGAINST {trade_count, total_notional, last_traded_at}]->
(:Trader)
```

**pgvector regime features**

`regime_snapshot.features` is planned as a normalized `VECTOR(6)` with an HNSW index using cosine distance:

```text
[spread, order_book_imbalance, vwap_drift,
 trade_velocity, depth_ratio, realized_volatility]
```

## System Architecture

```text
+--------------------------------------------------------------------+
| TIER 1: PRESENTATION (Next.js)                                       |
| Trading terminal | Query/optimizer lab | Surveillance console       |
+--------------------------------------------------------------------+
                              |
                  REST / WebSocket order submission
                              v
+--------------------------------------------------------------------+
| TIER 2: PRE-TRADE RISK AND ACCESS CONTROL (FastAPI + PostgreSQL)      |
| Login -> bcrypt verification -> role-scoped JWT                     |
| BEGIN -> SET LOCAL app.role -> lock account -> verify balance       |
|       -> escrow funds -> INSERT order (OPEN) -> COMMIT               |
+--------------------------------------------------------------------+
                              |
                       Only after commit
                              v
+--------------------------------------------------------------------+
| TIER 3: MATCHING AND IN-MEMORY ANALYTICS (single writer)              |
| Price-indexed linked lists | Fixed-point prices                     |
| Prefix-sum ring buffer (VWAP) | Fenwick tree (price-band volume)     |
+--------------------------------------------------------------------+
                              |
                     Immutable TradeEvent
                              v
+--------------------------------------------------------------------+
| TIER 4: ASYNCHRONOUS SETTLEMENT AND SURVEILLANCE                      |
| PostgreSQL: settlement and trigger-maintained positions             |
| Redis: top-20 order-book depth                                      |
| Neo4j: EXECUTED_AGAINST graph and cycle search                       |
| pgvector: regime vectors and HNSW similarity search                 |
+--------------------------------------------------------------------+
```

The processing path flows downward. Tier 3 emits events without depending synchronously on Tier 4 components; downstream consumers are intended to operate without blocking matching.

## System Flow

1. **Authentication:** Verify the user's bcrypt password hash against stored credentials and issue a JWT containing the user's role.
2. **Order submission:** The gateway calls `place_and_reserve_order()`. The transaction locks the account, verifies the balance, escrows funds, and inserts the order.
3. **Matching:** Pass the committed order to the engine. Match against resting orders using price-time priority, emitting a `TradeEvent` for each fill.
4. **Settlement:** `settle_execution()` locks both counterparties in ascending ID order and moves funds atomically. The position trigger updates positions and realized P&L.
5. **Asynchronous fan-out:** Update Redis depth and remove empty levels; create or increment the Neo4j counterparty edge; compute and upsert regime feature vectors at a fixed interval.
6. **Presentation:** Show fills and settled balances to traders. Allow compliance users to query trading cycles and similar historical market regimes.

## Optimizations

The following are planned techniques and expected properties, not benchmark results.

### Matching Engine

| Optimization | Technique | Intended benefit |
| --- | --- | --- |
| Order-book layout | Price-to-linked-list map and order-ID index | O(1) operations at an identified price level; direct cancellation |
| Money arithmetic | Integer prices and quantities | Exact tick/lot arithmetic without floating-point drift |
| Rolling VWAP | Prefix-sum ring buffer | O(1) window query |
| Price-band volume | Fenwick tree over price buckets | O(log M) queries and updates |
| Latency isolation | Single writer, no I/O on the hot path, asynchronous event emission | Keep downstream load off the matching path |

### Transactions and Concurrency

| Optimization | Technique | Intended benefit |
| --- | --- | --- |
| Atomic balance reservation | `SELECT ... FOR UPDATE` inside one transaction | Prevent concurrent double-spending |
| Deadlock avoidance | Lock settlement accounts in ascending trader ID order | Eliminate circular waits between those account locks |
| Position maintenance | `AFTER INSERT` trigger on `execution` | Keep positions and P&L consistent with trade records |
| Hot-table size | Move resolved orders to `order_history` and delete them from `order` | Reduce active-table size and relevant scan costs |

### Data Access and Storage

| Optimization | Technique | Intended benefit |
| --- | --- | --- |
| Live depth reads | Redis sorted sets; retain top-20 levels per side and evict empty levels | Target sub-millisecond depth reads |
| Counterparty graph size | `MERGE` a weighted edge per trader pair | Aggregate trade count and notional instead of creating one edge per trade |
| Cycle detection | Variable-length Cypher traversal | Express closed-ring detection without repeated SQL self-joins |
| Similarity search | HNSW with cosine distance on `VECTOR(6)` | Approximate nearest-neighbor lookup without exhaustive comparison |
| Disclosure search | `tsvector` column and GIN index | Indexed full-text lookup |
| Query-path selection | Compare B-tree, BRIN, and covering indexes with `EXPLAIN ANALYZE` | Verify index choices against actual query plans |

### Integrity and Security

| Optimization | Technique | Intended benefit |
| --- | --- | --- |
| Layered role enforcement | JWT validation plus PostgreSQL roles and row-level security | Enforce compliance restrictions at application and database layers |
| Credential handling | Bcrypt password hashes and environment-based secrets | Keep plaintext passwords and hardcoded secrets out of source |
| Constraint-based validation | `CHECK`, `FOREIGN KEY`, and `UNIQUE` constraints | Reject invalid rows at the database boundary |

## Future Work

The matching tier is designed to be independently replaceable. Potential improvements, in order, are:

1. **Native order book:** Reimplement in Rust or C++, exposed through PyO3 bindings or a thin IPC boundary. Rust can encode ownership constraints in the type system.
2. **Cache-conscious memory layout:** Replace pointer-linked nodes with a contiguous arena or flat per-price-level arrays.
3. **Allocation-free hot path:** Preallocate order and price-level pools at startup.
4. **Lock-free analytics reads:** Publish analytics state through single-producer, multiple-consumer structures without blocking the writer.
5. **Vectorized range scans:** Use SIMD over contiguous price buckets for batched band-volume calculations.
6. **Lower-overhead transport:** Evaluate shared memory or `io_uring` if gateway-to-engine transport becomes the dominant cost.
7. **Replayable market data:** Drive the engine deterministically from recorded order flow to support regression benchmarks.

## Tech Stack

| Layer | Planned technology |
| --- | --- |
| Frontend | Next.js, TypeScript |
| API | FastAPI |
| Authentication | Bcrypt, JWT |
| System of record | PostgreSQL with pgvector |
| Matching engine | Standalone in-memory Python engine |
| Cache | Redis |
| Graph | Neo4j |
| Day 1 infrastructure | Native PostgreSQL with pgvector |

## Getting Started

Day 1 uses Python 3, Git, and native PostgreSQL with pgvector. Redis and Neo4j are part of later development phases.

### 1. Prepare native PostgreSQL

On macOS with Homebrew, install PostgreSQL 17 and pgvector if you need a new local instance. [PostgreSQL 17 formula](https://formulae.brew.sh/formula/postgresql@17) and [pgvector formula](https://formulae.brew.sh/formula/pgvector).

```bash
brew install postgresql@17 pgvector
export PATH="$(brew --prefix postgresql@17)/bin:$PATH"
brew services start postgresql@17
pg_isready -h /tmp -p 5432
```

The default connection uses the `/tmp` socket, port `5432`, and your macOS username as the PostgreSQL administrator. Check for the project database.

```bash
psql -h /tmp -p 5432 -d postgres -c "SELECT datname FROM pg_database WHERE datname = 'tradegraph';"
```

If the query returns zero rows, create the database.

```bash
createdb -h /tmp -p 5432 tradegraph
```

### 2. Configure the local environment

```bash
test -f .env || cp .env.example .env
```

If your native PostgreSQL connection differs from the defaults, use the matching options in `psql` and `createdb`, and set `POSTGRES_ADMIN_HOST`, `POSTGRES_ADMIN_USER`, `POSTGRES_PORT`, or `POSTGRES_DB` in `.env` as needed. For a local server that requires a password, configure libpq's `.pgpass`. Keep `.env` out of Git.

### 3. Install the Day 1 dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### 4. Initialize a fresh local database

```bash
bash scripts/setup_day1.sh
```

With the native PostgreSQL server running, the script applies the schema and reference rows in one transaction, prompts for synthetic trader and compliance passwords, and runs the verifier and integration tests. It stops if the selected database already contains public tables.

### 5. Verify an initialized Day 1 database

```bash
python scripts/verify_schema.py
python -m pytest -m day1
```

If the current schema was installed and setup stopped at the demo password prompt, resume with `python scripts/seed_demo_accounts.py`. It creates Alice, Bob, and Carol as traders and one compliance administrator. Reruns preserve existing login passwords, balances, and manager assignments.

### Planned application startup

The following commands are for the later application phases.

Backend, from the repository root with the virtual environment activated.

```bash
uvicorn backend.api.main:app --reload
```

Frontend, from a separate terminal.

```bash
cd frontend
npm install
npm run dev
```
