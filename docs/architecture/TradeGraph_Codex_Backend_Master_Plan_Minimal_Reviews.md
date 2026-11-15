# TradeGraph — Codex Backend Master Implementation Plan (Source-Aligned, Two Planned Reviews)

**Scope:** backend, contracts, relational schema/ER alignment, in-memory algorithms, advanced SQL, Redis, Neo4j, pgvector, testing, simulator and backend documentation. **Out of scope:** the Next.js frontend and production-grade scalability or microsecond-latency guarantees.

**Repository:** `https://github.com/SudarshanG9/TradeGraph`  
**Audited reference:** `main` at `1a5fa87c83b5888eecdbef3bf27b203e91a49eb3` (November 14, 2026). **Codex must first inspect the actual local clone:** local changes and newer commits override this snapshot.  
**Source of truth (in priority order):** (1) the **23-page original** `tradegraph-architecture-plan.md (1)(1).pdf` / identical `tradegraph-architecture-plan.md.pdf`, particularly §§2–10; (2) the **5-page** `DBMS Level 3 Project Requirements.pdf`; (3) existing live repository files (`db/schema.sql`, ER markdown, decisions, and implementation); (4) this Codex execution document only as a detailed translation. The original architecture is not permission to replace currently working code. Any conflict is a human approval gate, not a cue to improvise.  
**Execution mode:** One Codex session, **12 sequential technical phases (0–11)**, but only **two planned human review checkpoints**: after Phase 1 and after Phase 11. Each phase retains its own mandatory tests and evidence; passing phases advance automatically *within the authorized batch*. **The user alone commits and pushes.** Unexpected architectural conflicts and unresolvable blockers are exception stops, not scheduled reviews.

---

## Execution gate protocol — controlling instructions (read first)

**The original implementation plan remains the source of truth for feature scope, technological choices and order.** This revision changes **only human review frequency**; it does not merge away technical phases, tests, deliverables or source-day sequence. The source's Day 1–6 backend outputs, plus Day 8 backend integration/performance evidence, remain mandatory; Days 7–8 frontend work remains explicitly deferred.

**Batch A (first prompt): Phases 0 and 1.** Execute Phase 0 strictly read-only, immediately continue into Phase 1 if the baseline is safe, and **STOP once after Phase 1** for contract/ER/infrastructure review. Phase 0 must retain its distinct read-only audit report; no user intervention is needed between these two phases. If the existing schema, financial model or local uncommitted work makes Phase 1 unsafe, STOP before editing and report the conflict.

**Batch B (second prompt, only after Batch A approval): Phases 2 through 11, continuously in ascending order.** At each phase boundary, run the specified focused tests and relevant regressions; write a phase-completion evidence entry into `docs/architecture/backend-implementation-progress.md` (new file within existing directory) and continue **without requesting review** only if that phase passes. Each phase's tests and deliverables are required, not merely optional progress reports. The final **STOP after Phase 11** is the second planned human review.

**Exception-stop policy:** Stop immediately, at any phase, only when (a) changing the 13-table ER, table/column/key/relationship or a frozen public contract is necessary; (b) the partial-fill fee, seller-collateral or event-loss semantics cannot be reconciled with the approved contract; (c) an unapproved new root-level file, directory, datastore, graph entity or architectural substitution would be required; (d) tests cannot be made to pass without weakening or deleting tests, or required services/credentials are genuinely unavailable; (e) continued steps risk losing existing user data, secrets or uncommitted work. Diagnose the blocker, list options, and await the user's decision. Do not count such unexpected stops toward the two planned reviews.

**No Git actions:** Do not run `git add`, `git commit`, `git push`, `git checkout`, `git reset`, `git clean`, `git stash` or mutate GitHub; human retains all commit/push control. Read-only `git status`, `git diff`, `git log` and `git ls-files` are allowed. **Do not edit `frontend/`.** New files must remain in the existing relevant directories, except root-level `docker-compose.yml` expressly required by the original plan.

**Phase-gate precedence:** Where older wording below says `STOP`, `Implement Phase N ONLY`, `user reviews after each phase`, or `do not start Phase N+1`, interpret it as **record evidence and advance under the approved batch**, except at the two scheduled review gates or the exception-stop conditions above. The detailed phase deliverables, definitions of done, original sequence and per-phase tests do **not** change.

---

## 0. Copy this as the Codex master instruction

> You are the backend implementation engineer for TradeGraph. Work ONLY in the current local clone; verify `pwd`, Git root, branch, `git status --short`, recent commits, and the current tracked tree before editing. **Never execute `git commit`, `git push`, `git add`, `git reset`, `git clean`, `git checkout`, `git switch`, `git stash`, force operations, or remote mutation.** The human user reviews at the two planned checkpoints and alone decides when to commit and push. Never edit GitHub remotely.
>
> Implement ONLY the explicitly authorized **batch**: Batch A = Phases 0–1; Batch B = Phases 2–11 after Batch A approval. Never run Batch B without approval; within an authorized batch, advance through numbered phases automatically only after a verified PASS gate. Before writing code, restate the phase goal, the exact existing files you will modify, any proposed new files with full paths, the interfaces you will consume or publish, the SQL objects affected, the test plan, and risks. Inspect the actual files first; do not overwrite existing working code, change a published contract, or duplicate already-implemented logic. Keep the current package/directory layout. **Never modify `frontend/`**. New files may be added only inside existing `backend/`, `db/`, `scripts/`, `tests/`, or `docs/architecture/` directories, as appropriate to their function; do not invent new directories or root-level files without explicit user approval. The **sole pre-authorized new root-level file** is `docker-compose.yml`, expressly prescribed in the original Day 1 plan; it must use the existing `.env.example` configuration and no committed secrets. Otherwise create new files only under existing appropriate directories. The original service-stack deliverable is **required**, not optional; do not silently relocate it to `scripts/`. If local native PostgreSQL is already configured, support it without destroying or silently replacing it.
>
> Preserve the **13-table PostgreSQL ER design**, existing table names/relationships, the two established role identities and existing public interfaces unless the user expressly approves a change. Before any proposed schema/table/column/key change, provide a concise compatibility impact assessment and STOP for approval. No fourteenth table, no speculative schema rewrites, no new ORM-generated migration baseline. Adding implementation SQL for functions, views, triggers, grants, policies and indexes inside existing folders is permitted when compatible. Document deviations from the architecture plan instead of silently making them.
>
> Use exact integer/fixed-point arithmetic for monetary amounts and prices; enforce role-scoped access; keep the in-memory matcher free of database and network operations; separate asynchronous consumers from the matching hot path. Use parameterized queries and secrets from environment variables. Preserve and extend existing tests; never delete, loosen, skip or rewrite a failing test merely to get a green run. Never claim tests passed unless you executed them and captured results. Never claim performance numbers unless benchmarked.
>
> At every phase completion: run the phase's focused tests plus relevant baseline regressions; record changed/created files, exact test results, blockers, assumptions, design deviations, `git diff --stat` and `git status --short` in the progress log. Proceed automatically to the next phase within the authorized batch only if PASS; stop at the Batch A or Batch B review gate, or on an exception condition. Never commit or push.

### Human-to-Codex batch invocation

**Prompt 1 (only planned review after Phases 0–1):**

```text
Read docs/architecture/TradeGraph_Codex_Backend_Master_Plan_Minimal_Reviews.md fully.
Execute Batch A: Phase 0 (strictly read only), then Phase 1.
Follow the original source-day sequence and every phase-specific acceptance test.
Do not ask for approval after Phase 0 unless a genuine exception blocker arises.
STOP after Phase 1 with the frozen contracts, preserved ER evidence,
infrastructure results, exact test commands/output and complete local diff.
Do not execute Phase 2 until I approve. Never commit, stage or push.
```

**Prompt 2 (only after your explicit approval of Batch A):**

```text
Batch A is approved. Execute Batch B: Phases 2,3,4,5,6,7,8,9,10,11
IN THIS EXACT ORDER, one technical phase at a time, preserving every original
requirement, test, and source-to-phase mapping. Automatically continue after
an internally verified PASS; record each phase's evidence in
`docs/architecture/backend-implementation-progress.md`. Do not ask for review
between passing phases. If any exception-stop condition applies, stop and report
it; do not invent schema changes or conceal failing tests. STOP after Phase 11,
provide the final full diff/test/rubric audit. Do not stage, commit or push.
```

**Handoff rule:** The user decides when to commit/push after the two planned reviews. Codex never commits, pushes, or stages changes.

---

### Scope control and source-faithfulness guarantees

This document is a **backend-only execution subset** of the original eight-day design, **not a replacement architecture**. The original plan's Day 7–8 Next.js work remains **pending and excluded from this Codex run**, not dropped or declared optional. All backend objectives from Days 1–6 and backend integration/verification portions of Day 8 remain required. No production-grade scaling or unmeasured microsecond-latency promises are introduced.

**Rules for deviations:**

- **Preserve:** four tiers; exactly 13 PostgreSQL production tables; existing ER keys/relationships; one PostgreSQL system of record; current Python matching engine; a true prefix-sum VWAP ring, Fenwick BIT, Redis top-20, Neo4j cycle search, six-dimensional pgvector + HNSW, FTS, RLS and advanced SQL examples.
- **Permitted implementation clarifications:** deterministic fee arithmetic, Redis price ordering, event identifiers, structured API contracts, tests and operational instructions **only where needed to realize the source requirements**. These are not new research features.
- **Approval required:** any new PostgreSQL table/column/entity, any extra Neo4j node/relationship type, new project directories, replacing Python matching, introducing a different persistence technology, removing Redis/Neo4j/pgvector, or changing published financial semantics. Never force such changes for convenience.
- **No code-generation shortcuts:** do not fill empty files with no-op stubs and call them implemented; do not hardcode synthetic API results as if read from actual databases; do not fabricate benchmark or `EXPLAIN` output.
- **Frozen local workflow:** Codex may inspect/edit/test in the local clone **only** within an explicitly authorized batch. It never stages, commits or pushes. The user commits/pushes at their discretion after the scheduled reviews.

**Source-to-phase correspondence:** Source Day 1 → our Phases 0–1; Source Day 2 → Phase 2; Source Day 3 → Phase 3; Source Day 4 → Phases 4–5; Source Day 5 → Phases 6–7; Source Day 6 → Phase 8 and normalization/optimizer items in Phases 5/11; Source Days 7–8 frontend → intentionally deferred; Source Day 8 backend simulation and latency evidence → Phases 9–11. The subdivision retains technical test boundaries, not extra human review gates.

## 1. What exists now (do not rebuild it)

At the audited main commit, the repository contains **81 tracked files: 19 non-empty and 62 empty placeholders**. Key implemented components:

- `db/schema.sql`: 13 tables, 18 FK relationships as asserted by verifier, constraints, indexes, two native roles, RLS on `market_disclosure` and `regime_snapshot`, `VECTOR(6)`/HNSW and disclosure `tsvector`/GIN.
- `db/seed.sql`, `scripts/seed_demo_accounts.py`: instruments, desks, fee tiers, Alice/Bob/Carol demo traders and a compliance-admin account, passwords hashed with bcrypt.
- `db/procedures/place_and_reserve_order.sql`: transaction-scoped row locking on margin accounts, positive/valid fields, active instrument and lot-size validation, fixed-point notional and fee reserve, overflow rejection, order insertion; `SECURITY DEFINER` and restricted execution grants.
- `backend/matching/order_book.py`: real price-time FIFO book, linked price levels, order-ID index, bid/ask heaps, partial fills, cancellation, self-trade prevention, integer prices, depth and invariant diagnostics.
- `tests/unit/test_matching_engine.py`: a slow reference matcher and four randomized 2,000-order differential sequences, plus targeted tests.
- `tests/concurrency/test_reservation.py`: conflicting concurrent orders, rollback, fee, input and overflow tests.
- `tests/integration/test_database_integrity.py`, `tests/integration/test_rbac.py`: integrity, privilege, RLS, vector and generated-search-field checks.
- `docs/er/tradegraph-er.md`, `docs/architecture/day1-decisions.md`, `README.md`, `scripts/verify_schema.py`, `scripts/setup_day1.sh`.

**Current gaps:** `backend/api/`, `backend/auth/`, event/workers, clearing, store adapters, Fenwick/VWAP, settlement SQL, SQL analytics, Neo4j scripts, simulator, several test files are placeholders. `frontend/` is also placeholders and MUST NOT be touched in this backend sprint. There is no tracked Docker Compose or CI workflow. At the audited revision, `scripts/setup_day1.sh` applies `db/schema.sql` and `db/seed.sql` but does **not** install the separate reservation function; plan backend installation accordingly. Existing tests are *written*, not independently verified by this planning document.

### Golden rule: preservation

Reuse `Order`, `Fill`, `MatchResult`, `OrderBook.submit`, `.cancel`, `.depth`, and current ER entities. Do **not** replace the matching engine with an ORM, DB-backed matching, a heap-only alternative, or a third-party exchange library. Refactor only if an integration test demonstrates a concrete need, and keep its existing tests green.

---

## 2. Intended end system and four-tier architecture

TradeGraph simulates a financial exchange where users submit limit orders, the system prevents overspending, matches crossing orders under strict price-time priority, settles executions atomically, and exposes historical trading activity for graph/vector surveillance and query optimization.

```text
          [Future Next.js client — OUT OF SCOPE THIS SPRINT]
                            |
                       REST / JSON
                            v
TIER 2    FastAPI gateway + bcrypt/JWT + role authorization
          PostgreSQL place_and_reserve_order() with FOR UPDATE
          cash -> escrow + INSERT OPEN order, then COMMIT
                            |
           ONLY a committed risk-approved order proceeds
                            v
TIER 3    Single-writer in-memory OrderBook
          price -> FIFO doubly-linked list; order_id -> node
          bid/ask heap; integer ticks and quantities
          Fenwick price-band volume; prefix-sum VWAP ring
          immutable Fill / TradeEvent; NO SQL / Redis / Neo4j I/O
                            |
                   nonblocking event handoff
                            v
TIER 4    Asynchronous downstream consumers
            |             |             |               |
        PostgreSQL       Redis         Neo4j        pgvector / FTS
        execution,       live L2       trader       regime similarity,
        cash/escrow,     depth         graph,       disclosure search
        positions/PnL                  cycles
                            |
                   FastAPI query endpoints
```

### Intended demonstration

1. Run native PostgreSQL + pgvector, Redis, Neo4j, FastAPI and worker(s), with setup instructions reproducible locally.
2. Authenticate Alice as `TRADER`; receive a short-lived JWT tied to `user_account.id` and role.
3. Place Alice's BUY order; SQL atomically escrows sufficient cash under a row lock, commits and returns order ID.
4. Place Bob's crossing SELL order; the in-memory engine matches at the *resting order's price* (maker price), emits fill event(s), updates its in-memory book and analytics.
5. The settlement worker inserts `execution`, consumes/reallocates escrow, updates balances and positions, and finalizes order statuses **in one DB transaction**. Retries do not apply the same execution twice.
6. Redis shows price-ordered top-20 bids/asks reflecting submissions, fills and cancellations. Empty levels disappear.
7. Neo4j aggregates executed-against relationships; a seeded A→B→C→A cycle is queryable as a *surveillance candidate* (not evidence of misconduct).
8. Synthetic six-feature market snapshots are generated and stored in `regime_snapshot`; similarity queries order by HNSW cosine distance. Disclosure full-text search finds seeded data.
9. API-only, admin-only endpoints demonstrate role gating, `EXPLAIN ANALYZE` plans, recursive desk rollups, window-function VWAP, `HAVING`, set operations and archival.
10. A simulator and tests reproduce the scenario with clear pass/fail outputs. No UI is required yet; JSON endpoints, CLI demos and test artifacts provide proof.

### Strict layer boundaries

- **Tier 2 before Tier 3:** no uncommitted or rejected order enters `OrderBook`.
- **Tier 3 remains pure:** no `psycopg`, HTTP, Redis, Neo4j, sleeps, disk writes or `await` inside the matching algorithm.
- **Tier 4 downstream:** slow graph/vector/cache consumers do not block the matching engine. Do not claim that this implies full failure durability.
- **PostgreSQL authoritative:** financial state and executions reside in Postgres; Redis and Neo4j can be rebuilt from canonical sources.
- **Single matching owner:** one FastAPI service process / one matching coordinator for the academic demonstration; multiple Uvicorn worker processes with independent books are prohibited. Document `--workers 1`.

---

## 3. Frozen ER model: exactly 13 PostgreSQL tables

Treat the existing `docs/er/tradegraph-er.md` and `db/schema.sql` as the structural source of truth. **No extra SQL tables.** Maintain the following relationships and field semantics:

| Table | PK and relationships | Responsibility / invariants |
|---|---|---|
| `user_account` | UUID PK; unique email; role | Password hash; exactly `TRADER` or `COMPLIANCE_ADMIN`. No plaintext secrets. |
| `desk` | Integer PK, self-FK `parent_desk_id`, optional FK manager trader | Desk hierarchy; use a recursive CTE to roll up analytics; prevent/guard cycles. |
| `trader` | UUID PK; unique FK to `user_account`; FK to `desk` | Distinct trading identity; admin user need not have a trader. |
| `kyc_profile` | `trader_id` PK/FK | Dependent identity record; synthetic hashes only. |
| `fee_tier` | Integer PK | Maker and taker fee schedules in `NUMERIC` basis points. |
| `margin_account` | `trader_id` PK/FK; FK `fee_tier_id` | BIGINT available cash and escrow; both nonnegative. |
| `instrument` | Integer PK; unique symbol | `tick_size` (minor units per tick), `lot_size`, active flag. |
| `order` | BIGSERIAL PK; FK trader/instrument | Active orders, integer ticks/quantity, filled quantity and OPEN/PARTIAL/FILLED/CANCELLED status. |
| `order_history` | Original order ID as PK | Retained closed orders; no independently generated ID. |
| `execution` | BIGSERIAL PK; FK instrument, buy/sell traders | Immutable matched fill: order IDs, counterparties, executed ticks/quantity/time; self-trade forbidden. |
| `position` | Composite PK `(trader_id,instrument_id)` | Net signed quantity and **gross** realized PnL (define precise algorithm; no fictional stored cost-basis column). |
| `market_disclosure` | BIGSERIAL PK; optional instrument FK | Generated `body_tsv` + GIN; admin-only via roles/RLS. |
| `regime_snapshot` | BIGSERIAL PK; instrument FK; `(instrument_id,captured_at)` unique | `VECTOR(6)`, HNSW cosine similarity; admin-only via roles/RLS. |

**Do not change** PK/FK cardinalities, names, status enum, `VECTOR(6)` dimension, RLS or existing check constraints. The current `execution.buy_order_id` and `sell_order_id` are intentionally not foreign keys: archival would otherwise invalidate references. Do not add such FKs. A user-account role and PostgreSQL role are different concepts; retain both.

**Normalization documentation must be honest:** `TRADER_DESK_ASSIGNMENTS` is a *hypothetical* BCNF-violating denormalized relation, not a fourteenth production table. Likewise, demonstrate 4NF issues in a hypothetical combined relation, not by claiming that normalized `margin_account` and `position` violate 4NF. The FD `order_id → tier_id → maker_fee_bps` belongs to a hypothetical joined/denormalized relation, not the actual `order` table.

---

## 4. Contracts and accounting policy (freeze BEFORE implementation)

These are *implementation decisions needed to make the source architecture executable*, not facts already proven by the existing source. Codex must write them into `docs/architecture/backend-contracts.md` in Phase 1 and test them. If they contradict the current local code, flag rather than silently change behavior.

### 4.1 Numeric units and price rules

- `price_ticks`: integer number of ticks, never float. `instrument.tick_size`: integer minor currency units per tick.
- `quantity`: integer units, positive and divisible by instrument `lot_size`.
- `notional_minor = price_ticks × tick_size × quantity` computed with overflow-safe integers/SQL `NUMERIC`; cast to BIGINT only after range validation.
- Fees use `fee_bps` and `CEIL(notional_minor × fee_bps / 10000)`; existing reservation uses **maximum** maker/taker bps as a conservative upper bound.
- All monetary balances and realized PnL use **BIGINT minor units**. No binary floats for accounting; Python `Decimal` or integer rationals for basis-point/weighted-average intermediate math. Unit tests cover large amounts and rounding.

### 4.2 Order state machine

```text
accepted + reserved -> OPEN
OPEN -> PARTIAL (some quantity filled)
OPEN/PARTIAL -> FILLED (filled_quantity == quantity)
OPEN/PARTIAL -> CANCELLED (remaining quantity released)
FILLED/CANCELLED -> order_history (archive after terminal processing)
```

A self-trade prevention event cancels **only the remaining incoming quantity**; fills that occurred against other traders first remain valid. Do not return escrow twice when cancellation and settlement race. `filled_quantity` must monotonically increase, never exceed `quantity`. Do not archive an order before all applicable settlements and account updates have committed.

### 4.3 Explicit academic collateral model — preserve existing reservation policy

`place_and_reserve_order()` currently reserves cash collateral for **both BUY and SELL** orders. Preserve this for the demo; do not silently switch SELL to inventory reservation or add an inventory/loan table. State plainly that SELL can create negative positions (collateralized synthetic short selling) and is **not a production margin engine**.

For a still-open order of remaining quantity `q` at its limit ticks `p`, the following is the **candidate reservation invariant inherited from the existing Day 2 routine** (subject to review of the actual fee basis):

`R(q) = p × tick_size × q + ceil((p × tick_size × q) × worst_case_fee_bps / 10000)`.

A fill of quantity `f` must release **exactly** `R(q_before) - R(q_after)` from that order's reserved escrow (subject to a fixed fee tier and a well-defined original reservation). This ensures that splitting a fill into many pieces does not produce extra collateral by repeated rounding. **Critical: do NOT equate this reserve release with actual charged maker/taker fees.** Actual fee rounding across partial fills has to be defined separately and proven within the available reserve for *every partition*. An exact fee-by-fill policy may need cumulative notional / historical fee state not currently persisted. Codex must present a small worked buyer/seller ledger, covering a single large fill versus 100 tiny partial fills, and **STOP for approval** if exact maker/taker accounting cannot be computed deterministically from the existing 13 tables and agreed event parameters. Never produce a compensating negative balance or quietly cap a fee without the user's explicit accounting decision. Do **not** calculate a fresh `ceil` per fill and accidentally strand escrow. Fee tiers must remain stable while orders are open, or the implementation must capture/derive a historical fee basis without modifying the ER; for the 24-hour academic build, explicitly **disallow fee-tier mutation while a trader has an OPEN/PARTIAL order**.

At execution tick price `p_exec` and `f` units, `trade_value = p_exec × tick_size × f`.

- **Buyer:** remove the per-fill released amount from their escrow, credit unused reserve to available cash, and permanently spend `trade_value + buyer_actual_fee`.
- **Seller:** remove the per-fill released collateral from escrow, return collateral to available cash, credit sale proceeds, and charge `seller_actual_fee`.
- Both accounts stay nonnegative in cash and escrow. Use the same fee and rounding policy consistently in settlement, simulator and tests.
- Expected combined account conservation for two counterparties: total `(cash+escrow)` changes by **minus buyer and seller fees** only; exchange fee revenue is a documented external sink because the frozen ER has no fee-revenue ledger.
- On cancellation release `R(q_remaining)` and set remaining reserved amount to zero. For partially filled orders only the **unfilled** collateral is released.

**Critical implementation nuance:** `margin_account.escrow_balance` is an account-level pool; the current `order` does not store per-order reserved fee snapshots. Never mistake pooled escrow for one order's escrow. Resolve reserve deltas from immutable order limit/quantity and a fixed fee-tier policy, lock the correct order/account rows, and document the assumption. If the model cannot be made consistent for a particular case using the existing columns, stop for a design decision rather than inventing a new table.

### 4.4 Execution identity, idempotency and crash boundary

- Immutable event schema: `TradeEvent(event_id, instrument_id, buy_order_id, sell_order_id, buy_trader_id, sell_trader_id, price_ticks, quantity, taker_order_id, occurred_at)`; exact Python names/typing frozen in Phase 1. `event_id` is stable across retries of the **same** fill. Separate API order request IDs from execution IDs.
- Use the existing `execution.id` BIGINT primary key as a stable execution identifier. An implementation may preallocate a sequence ID before queueing, then insert using that specific ID; a duplicate event ID must be a harmless no-op, not a second financial transfer. Preallocation is an API/dispatcher task, **never an order-book operation**.
- The settlement SQL routine must check already-settled event identity, validate order IDs, counterparties, price/quantity/remaining capacity, lock accounts in **ascending trader UUID** order and orders in a consistent deterministic order, then update all financial/record state in one transaction.
- Settlement worker acknowledges success only after commit. Derived-store consumers operate only on **settled** execution facts; they must not publish a trade as settled before the DB succeeds.
- The academic demonstrator may use an in-process `asyncio.Queue` for a nonblocking downstream handoff only if the review explicitly accepts its limitation. **It is not crash-durable and cannot, by itself, satisfy the original plan's “never lose financial state” language.** State this openly. A process crash between risk reservation and settlement can require explicit reconciliation/replay. Do not claim exactly-once delivery or production recovery without a persistent, tested mechanism. Idempotent settlement under retries while the process lives is still mandatory.
- If a queue/worker fails, fail closed: expose unhealthy state and stop accepting new trading requests; never silently drop a money-moving execution. For the demo, a bounded workload and a single settlement worker are acceptable. Protect against unbounded production claims.

### 4.5 Position and realized-PnL policy compatible with existing ER

The `position` table has `net_quantity` and `realized_pnl`, **not stored average cost**. Therefore a correct realization algorithm must not silently assume such a column exists.

Implement an **auditable historical recomputation** of gross realized PnL for each affected `(trader,instrument)` after execution insertion, using signed execution quantities and a documented **weighted-average entry-cost** algorithm. Recompute from that trader's executions in stable deterministic order (e.g. settlement execution ID under a single settlement writer). For each signed trade delta:

1. If entering or increasing a same-direction position, update weighted average entry price.
2. If reducing an existing position, realized gross PnL on closed units equals closed quantity × `(exit_price - average_entry_price)` for a long, or × `(average_entry_price - exit_price)` for a short.
3. If crossing through zero, realize the closing part, then open the remainder in the new direction at the new execution price.
4. Persist only net signed quantity and gross realized PnL to the existing table. Cash fees are separately deducted from balances; realized PnL is labelled **gross, excluding fees**.

This is O(number of historical executions per affected position), acceptable for a small academic dataset, and structurally honest. Do not claim O(1) cost-basis maintenance without an additional approved persistent cost-basis field. Tests must include long open/close, short cover, partial close, flip through zero and fee exclusion. A trigger can call the recomputation function after insertion; avoid recursive trigger calls and check transaction ordering.

### 4.6 Authentication and roles

- Demo account passwords are already bcrypt-hashed. Add `POST /login` returning a short-lived role-scoped JWT: `sub=user_account.id`, `role=TRADER|COMPLIANCE_ADMIN`, `exp`, `iat` (and optional issuer/audience).
- For all trader order endpoints, resolve `trader.id` **from the validated JWT subject**, not from a client-supplied trader UUID. Missing/invalid/expired token is 401; wrong role is 403.
- Use a dedicated **least-privileged runtime DB login** rather than the native PostgreSQL superuser used by Day 1 setup/tests; no client can call privileged `SECURITY DEFINER` functions with an arbitrary trader ID. Explicitly GRANT EXECUTE on reservation/settlement only to the approved service identity. Avoid adding new user-facing application roles.
- Within privileged DB operations, set `SET LOCAL app.role` and effective PG role appropriately in a transaction, so RLS and PostgreSQL GRANT checks both matter. `app.role` alone is spoofable and never establishes identity. Test `TRADER` blocked from admin tables even if request forges role, and admin access under the intended service identity.
- JWT signing key and database/Redis/Neo4j credentials come from `.env`; never print secrets or commit them. Use prepared/parameterized queries, not string interpolation of request data.

### 4.7 API and event contract (backend only)

Propose exactly the following stable JSON endpoints unless the current local clone already has a documented equivalent:

| Method/path | Role | Contract |
|---|---|---|
| `POST /login` | Public | email/password → signed JWT, role, expiry; no password/hash returned. |
| `GET /health` | Public/diagnostic | Live service status and separate PG/Redis/Neo4j dependency states; no credentials. |
| `POST /orders` | TRADER | `{instrument_id,side,price_ticks,quantity}` → `{order_id,status,accepted_at}`; trader from JWT. |
| `POST /orders/{id}/cancel` | TRADER owner | Cancel remaining quantity; release unused escrow; return final status. |
| `GET /orders/me` | TRADER | Own active + recent archived order summaries. |
| `GET /account/me` | TRADER | Own cash, escrow and positions; PostgreSQL source. |
| `GET /market/{symbol}/book` | Authenticated | Top-20 bids/asks and freshness; Redis-derived cache. |
| `GET /market/{symbol}/trades` | Authenticated | Settled execution records; PostgreSQL source. |
| `GET /market/{symbol}/analytics` | Authenticated | Rolling in-memory VWAP and price-band volume. |
| `GET /admin/surveillance/cycles` | COMPLIANCE_ADMIN | Neo4j ring candidates with trader IDs/counts. |
| `GET /admin/regimes/similar` | COMPLIANCE_ADMIN | `instrument_id`, six-vector or current snapshot query, top-k cosine matches. |
| `GET /admin/disclosures/search` | COMPLIANCE_ADMIN | Full-text ranked results; parameterized query. |
| `GET /admin/optimizer/compare` | COMPLIANCE_ADMIN | Named query scenarios and actual `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` results. |
| `GET /admin/desks/rollup` | COMPLIANCE_ADMIN | Recursive desk PnL and execution volume rollup. |

Use Pydantic request/response models (in existing `backend/api/` modules or a new file **inside that already-existing directory** if unavoidable). Price/quantity fields are integers; explicit max values and validation. Include timestamps in UTC ISO-8601, stable machine-readable error codes, and OpenAPI documentation. A `POST /login` route can live in `backend/api/routes/auth.py` without an extra `/auth` prefix. Do not implement UI, WebSockets or user self-registration in this sprint.

---
## 5. Technical selections: data structures, algorithms and their trade-offs

### 5.1 OrderBook: priority queue of price levels + FIFO linked lists

**Existing implementation to preserve:** `backend/matching/order_book.py`.

- `dict[(instrument_id, side, price_ticks)] → _PriceLevel`: O(1) average lookup of an existing price level.
- `_PriceLevel` is a **doubly linked FIFO list**. New resting orders append to its tail; matching removes/reduces the oldest head. This enforces time priority at equal prices and supports O(1) removal of a known node.
- `dict[order_id] → (level_key, node)`: O(1) average direct cancellation without traversing the list.
- Per-instrument bid/ask **binary heaps**: highest bid represented by negative price, lowest ask by positive price; O(log P) insertion of a new price level, O(1) best-level peek excluding lazy invalidations, and amortized cleanup of stale heap prices. P = distinct tracked price levels. It is inaccurate to promise O(1) total placement at all possible new price levels.
- Incoming BUY crosses only if `bid_limit ≥ best_ask`; incoming SELL crosses only if `ask_limit ≤ best_bid`; execution uses the **resting maker's price**.
- A same-trader opposing resting order triggers incoming-residual self-trade prevention, preserving earlier legitimate fills. Do not let self-trades insert an `execution`.
- `depth()` currently scans level maps and sorts. Keep this as a diagnostic/source snapshot; Redis caches top-20 for API reads.
- Keep order IDs unique for the lifetime of a book (`_seen_ids`), and retain invariant checks off the hot path.

**Tests:** price priority, FIFO, partial fill, cancellation O(1) data-structure path, self-trade prevention, independent symbols, stale heap reuse and randomized differential runs. Run tests after every matching-engine change.

### 5.2 Fenwick Tree / Binary Indexed Tree (BIT)

**Location:** `backend/matching/fenwick.py` (currently empty). **Purpose:** aggregate *executed trading quantity* per instrument/price band, not orders currently resting in the book (that is Redis depth).

- An array/BIT stores prefix sums of volumes. Point update at compressed bucket index `i` repeatedly adds `i & -i`; prefix query repeatedly subtracts `i & -i`.
- Range volume `[L,R] = prefix(R) - prefix(L-1)`. Both update and query cost O(log M) for M indexed price buckets; memory O(M).
- Price levels arrive dynamically, so **decide and document** the index universe. Prefer stable instrument-specific tick-bucket mapping from known synthetic dataset/ranges in the demonstration. If supporting truly unseen ticks with coordinate compression, explicitly implement/test a correct rebuild or mapping expansion and disclose that a rebuild costs more than O(log M). Do not silently map two distinct price ticks to the same bucket or drop out-of-range fills.
- The analytics owner updates BIT once per **settled fill**, not twice on both buy and sell legs. Use event IDs to prevent double-counting on a retry.
- Tests: prefix/range results vs brute-force dictionary, empty range, boundaries, repeated price, negative prices rejected, large quantities, reindex/expansion if supported, per-instrument separation.

### 5.3 Prefix-sum ring-buffer rolling VWAP

**Location:** `backend/matching/rolling_vwap.py` (currently empty). VWAP = `Σ(price × quantity) / Σ(quantity)` for a window of the last N executed fills; use price ticks (or documented minor-price units) consistently.

- Implement the **exact original algorithmic artifact**: fixed-capacity **cumulative-prefix circular buffer**, storing monotonic cumulative `Σ(p×q)` and `Σq` with correct prefix subtraction for the last `N` fills (and a small sentinel/baseline for evicted entries). Add/query O(1) independent of `N`, with documented wraparound invariants.
- A plain running-sum queue may have the same asymptotics but does **not** fulfill the original *prefix-sum ring buffer* implementation requirement. Do not substitute it. Prove correct prefix differences on wraparound and eviction.
- Use integer sums and `Decimal` at presentation boundary. Return `None` (not divide-by-zero) when total volume = 0.
- Keep this **last-N-fills VWAP** distinct from the separate SQL rolling **10-minute** VWAP window-function query. Do not mislabel one as the other.
- Tests: first fill, variable quantity, wraparound, evictions, zero volume, precision, seeded reference values.

### 5.4 SQL transaction strategy

- PostgreSQL `SELECT ... FOR UPDATE` is a **pessimistic row lock**. For the same trader's funds, it serializes check→reserve; two concurrent orders cannot both spend one balance.
- For settlement involving two accounts, lock by **ascending stable trader UUID** order, then lock order rows in a fixed order. The purpose is to prevent cyclic wait-for dependencies. Lock ordering eliminates this specific account-lock deadlock pattern; do not assert “deadlock-free under every possible database interaction.”
- Keep escrow adjustments, terminal status changes, `execution` insert, and position trigger in **one transaction**. Any failure rolls back everything.
- `SECURITY DEFINER` routines use qualified object names and safe `search_path` already demonstrated by reservation. Scope execution grants to the authenticated service DB identity.
- Persistent audit of financial cash transfers beyond the existing `execution`, `order`, `margin_account` and `position` fields is **not** available in this frozen schema; document that limitation rather than inventing a ledger.
- Use `FOR UPDATE` under concurrent reservations and settlement; test race conditions in real PostgreSQL, not a mocked connection.

### 5.5 Event dispatch and consistency boundaries

**Locations:** `backend/events/trade_event.py`, `backend/events/dispatcher.py`, `backend/workers/settlement_worker.py`.

- Publish immutable events at the application orchestration boundary; the order book itself merely returns deterministic `Fill` objects.
- A single-writer order-processing coordinator serializes all `OrderBook.submit/cancel` calls. It should never await external services while holding the in-memory matching turn.
- Use a carefully controlled `asyncio.Queue` or dedicated worker queue for handoff. **Don't block inside matching** on slow settlement/graph queries; reserve capacity or check queue backpressure *before* modifying the book; if enqueue fails after a match, fail closed and report that this is not crash-durable. Never silently drop a fill; gateway-level requests may await a settlement result only for user-facing confirmation, but isolate measurements of matching latency from end-to-end latency.
- The **settlement worker** consumes fills and makes PostgreSQL authoritative. **Cache/graph/vector workers** consume settled facts, not raw uncommitted fills. This avoids showing trades that failed settlement.
- Explicitly classify failure modes: malformed order rejected before reservation; reservation DB failure leaves no book change; matching application error triggers safe remediation/refund; settlement retriable by stable event ID; slow Redis/Neo4j never invalidates cash; crash durability is **not claimed** for the in-memory queue.
- No hidden global singleton shared across multi-worker processes; one process/one writer for the demo.

### 5.6 Redis depth: correct sorted-set design

**Locations:** `backend/stores/redis_depth.py`, `backend/workers/cache_worker.py`.

The source plan's illustrative Redis sorted-set sketch placed **aggregate quantity in ZSET score** while using `ZREVRANGE` to claim best-price order. That would sort by quantity, **not price**. Correct the implementation intentionally and document the deviation:

- `depth:{symbol}:bids` / `depth:{symbol}:asks`: Redis ZSET, **score = integer price_ticks**, member = canonical string price ticks. Best bids use descending rank; asks ascending rank.
- `depth:{symbol}:bids:qty` / `depth:{symbol}:asks:qty`: Redis HASH `price_ticks → aggregate_resting_quantity`.
- Query ZSET top 20 in the right price direction and fetch associated quantities from HASH; serve sorted `(price_ticks, qty)` pairs.
- On submit, fill or cancellation, the worker updates the snapshot/changed levels. **Precision constraint:** Redis ZSET scores are floating-point; SQL `BIGINT` ticks above exact double-integer range must not be silently rounded. For the synthetic demonstration either enforce a documented safe tick-value range for this adapter (without silently narrowing the database schema), or use an order-preserving fixed-width lexicographic member encoding with a quantity hash. Test the chosen scheme. Use a Redis transaction/Lua where necessary so ZSET and HASH do not disagree. `ZREM` and `HDEL` empty levels; `DEL` empty instrument side keys.
- A rebuild from `OrderBook.depth` is acceptable for the academic demo, provided processing is ordered and the worker cannot apply stale snapshots after newer ones. Cache is derived, never authoritative.
- Performance claims must use actual measured Redis latency; do not print “sub-millisecond” without a benchmark.

### 5.7 Neo4j weighted counterparty graph and ring search

**Locations:** `backend/stores/neo4j_graph.py`, `backend/workers/graph_worker.py`, `db/neo4j/*.cypher`.

- Node `(:Trader {id, name})` mirrors Postgres trader UUID; uniqueness constraint.
- Directed relationship `(buyer)-[:EXECUTED_AGAINST {trade_count,total_notional,last_traded_at}]->(seller)` aggregates repeated trades. `MERGE` avoids creating a separate edge for each repeated pair; update count/notional on **new** settled executions.
- Detect 3-to-5-trader closed directed loops using a variable-length Cypher path query, with deduplication or limits so the demo is intelligible. A cycle is an indicator for investigation, not conclusive proof of wash trading.
- **Retry safety without changing the source graph model:** the source permits only `Trader` nodes and `EXECUTED_AGAINST` relationships. Preserve those structures; do not create `ProcessedExecution` nodes or another graph entity without approval. A new settled execution can use the source-prescribed `MERGE ... ON MATCH SET trade_count += 1` path, while a restart/reconciliation path may rebuild absolute aggregate weights from authoritative PostgreSQL `execution` rows. Prove that a replay/rebuild cannot double-count, and show the `MERGE` update itself in the syllabus demonstration.
- Seed an obvious Alice→Bob→Carol→Alice demo cycle, and add age-based deletion of stale demo graph edges; maintain a documented relation to Postgres execution history and rebuild behavior.

### 5.8 pgvector, HNSW and PostgreSQL full-text search

**Locations:** `backend/stores/regimes.py`, `backend/workers/regime_worker.py`, `db/queries/vector_similarity.sql`, `db/queries/full_text_search.sql`.

- The vector is **not an LLM embedding**; it is six deterministic, engineered and normalized microstructure measurements: `[spread, order_book_imbalance, vwap_drift, trade_velocity, depth_ratio, realized_volatility]`.
- Derive from real simulated order-book/trade observations. Define units, lookback lengths, normalization/clamping, missing-data defaults and divide-by-zero safeguards. Never label arbitrary random 6D vectors as calculated market microstructure.
- Upsert per `(instrument_id,captured_at)` via `INSERT ... ON CONFLICT DO UPDATE` during an interval; `DELETE` after the demo retention window.
- Similarity uses HNSW `vector_cosine_ops`, `ORDER BY features <=> query_vector LIMIT k`, optionally filtered by instrument. Return distance and metadata, not just an ID.
- HNSW is approximate nearest-neighbor indexing; on tiny datasets Postgres may choose a sequential scan. Verify index existence and functionality, not an invented acceleration factor.
- Disclosures: generated `body_tsv` with GIN index already exists. Implement `plainto_tsquery`/`websearch_to_tsquery` with safe parameters and relevance ranking; add sample disclosures only through legitimate admin-authorized flow. Test admin-only RLS on both data sets.

### 5.9 Advanced SQL and query optimization demonstrations

Keep each query in its current planned file under `db/queries/`:

- `order_archive.sql`: move eligible terminal orders to `order_history` in **one atomic CTE**, retaining original IDs, and delete only when financial finalization is committed.
- `price_band_having.sql`: grouped executed volume with `GROUP BY` and `HAVING` threshold.
- `recursive_desk_rollup.sql`: recursive desk hierarchy and SUM of position PnL/volume; handle/guard cycles.
- `rolling_vwap.sql`: SQL window function over the **last 10 minutes** using execution timestamps, value-weighted by quantity, carefully handling zero denominator and time-range frame semantics.
- `set_operations.sql`: meaningful `UNION`/`INTERSECT`/`EXCEPT` example on maker/taker or active/settled trader groups, with clear semantics.
- `full_text_search.sql`: indexed `tsvector`/GIN query with ranking and admin constraints.
- `vector_similarity.sql`: HNSW cosine nearest neighbors with relational filter and admin constraints.
- `db/views/order_book_view.sql`: explain whether the view represents **persisted active orders** vs the in-memory matching book; it is a SQL teaching artifact, **not the hot matching implementation**.

Use **real `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`** comparisons of sequential scan, B-tree index-assisted scan, a BRIN index on time-correlated execution data, and an `INCLUDE`/covering index for an appropriately selected lookup; also compare indexed SQL with in-memory band queries. New compatible indexes may be added in the existing `db/schema.sql` or an index-install SQL file in the existing `db/queries/` directory, without changing the 13-table ER. Do not pretend that BRIN or covering indexes always outperform a normal B-tree; their utility depends on physical correlation, selectivity and query projections. Use realistically seeded sample sizes and report actual planner choice, table cardinality, query cost and run time. Do not disable planner options on the application's main connection; if a forced seq scan is needed for a fair teaching comparison, scope `SET LOCAL enable_indexscan = off` etc to a read-only demonstration transaction and explicitly label it forced. The goal is a defensible explanation of *when* an index is useful, not fabricated speedups.

---

## 6. Phased implementation — source-ordered, local-only, human-gated

The original project plan starts from the ER/schema, then proves Tier 2 + Tier 3 independently, wires the gateway, brings settlement online, adds Redis/Neo4j, then pgvector/FTS. **Keep that dependency order.** These smaller phases allow one Codex session to act sequentially. Do not automatically continue if a phase is PASS: the user alone approves the next phase. Estimated durations, where supplied elsewhere, are *not* acceptance criteria.

### Phase 0 — Audit local clone and environment (READ ONLY; original Day 1 baseline)

**Files allowed to change:** NONE, including tracked files, local `.env`, and project docs. Use read-only Git and DB inspection. No service reset, schema creation, seeding, or destructive test without knowing its fixture behavior.

**Codex steps:**

1. Display `pwd`, `git rev-parse --show-toplevel`, current branch, HEAD, `git status --short`, tracked filenames and **existing uncommitted changes**. The remote audit noted 81 tracked files, 19 nonempty, 62 placeholders at `1a5fa87`; the *local* clone controls reality.
2. Read existing `db/schema.sql`, `db/seed.sql`, `docs/er/tradegraph-er.md`, `docs/architecture/day1-decisions.md`, `db/procedures/place_and_reserve_order.sql`, `backend/matching/order_book.py`, `README.md`, `scripts/setup_day1.sh`, `scripts/verify_schema.py`, all non-empty tests, and the architecture/rubric.
3. Map the existing 13 tables and current app roles and verify schema and ER agree; note any inconsistency rather than changing either.
4. Inspect the local Python environment and version, `.env` *presence but not secret values*, PostgreSQL/pgvector availability, Redis and Neo4j availability, and prerequisites for Compose.
5. Run the existing pure-Python matcher tests: `python -m pytest tests/unit/test_matching_engine.py -q`. If the local database is already initialized, run the safe verifier and applicable Day 1 tests; if not, record BLOCKED rather than creating/dropping a DB.
6. Inspect `pg_proc` catalog (read only) to determine whether the Day 2 reservation function is installed. The Day 1 setup currently does *not* install this function. Report baseline results honestly.
7. Produce an evidence table: existing/empty/missing, dependency available/unavailable, tests PASS/FAIL/BLOCKED, and recommended Phase 1 decisions.

**Gate:** No repo changes. Exact baseline captured. **RECORD PHASE PASS AND ADVANCE AUTOMATICALLY within Batch A, unless an exception blocker exists.**

### Phase 1 — Freeze contracts, preserve ER, and reproducible service setup (original Day 1 completion)

**Allowed tracked files:** `backend/config.py`, `backend/events/trade_event.py`, `.env.example`, `requirements.txt`, `pytest.ini`, `docs/architecture/day1-decisions.md` (only to document approved decisions), `scripts/setup_day1.sh` (only if actual safe bootstrap defect), plus the **new** `docs/architecture/backend-contracts.md` inside an existing directory. **Source-authorized new root file:** `docker-compose.yml` (original Day 1 deliverable). No other root-level additions without user approval.

**Decisions that must be documented before code changes:**

- Maintain all **13 PostgreSQL tables**, 2 PostgreSQL roles, 2 application roles and existing `RLS` policies. Freeze the existing ER exactly as implemented; `TRADER_DESK_ASSIGNMENTS` is a *hypothetical* normalization example, never a production table.
- Freeze financial units: `price_ticks` is a tick count; `instrument.tick_size` converts ticks to minor units; cash/escrow/PnL are integer minor units; `quantity` is integer units; `fee_tier` uses `NUMERIC` basis points. Do not use float for money.
- Freeze `Order`, `Fill`, `MatchResult`, order lifecycle, immutable `TradeEvent` typing and the commit-before-match ordering. The book should not know PostgreSQL, JWT, Redis, Neo4j or pgvector clients.
- Freeze event identity/replay approach using **existing** execution ID capacity; note explicitly that the original schema has no durable outbox. Present a reconciliation strategy and its precise limits before claiming any crash safety.
- Freeze buyer and seller collateral interpretation inherited from the reservation function; define cancellation and partial-fill cases; **separately** decide per-order fee aggregation/rounding and maker/taker roles. Demonstrate the 100-tiny-fills rounding counterexample before signoff. Where exact semantics cannot fit the fixed schema, obtain approval instead of inventing fields.
- Freeze actor identity: JWT subject is `user_account.id`; trader UUID resolved on server; DB `SET LOCAL app.role` is *not* authentication by itself; runtime connections must be least privileged.
- Freeze Redis `depth:{symbol}:{bids|asks}`, Neo4j Trader/EXECUTED_AGAINST, vector six-feature metadata, query result units and the planned REST API contracts in §4.7.

**Implementation tasks:**

1. Write `backend-contracts.md` with field-by-field examples of order, fill and settlement events; roles/HTTP status/errors; state transitions; per-store authoritative vs derived status; one-writer and ordering assumptions; no frontend implementation.
2. Implement immutable typed event objects in existing `backend/events/trade_event.py`; use existing `Fill` class rather than duplicate it. Add focused contract import/serialization tests in existing `tests/unit/test_matching.py`.
3. Implement environment-backed configuration in existing `backend/config.py`, with no live passwords in source, least-privileged runtime Postgres identity and health settings. Update `.env.example` with placeholders only.
4. Supply the exact original multi-service Compose topology **PostgreSQL + pgvector, Redis, Neo4j** from root `docker-compose.yml`, using environment variables for credentials and persistent data storage. Preserve native PostgreSQL compatibility for users who have a working local DB; do not overwrite an existing instance. Verify config with `docker compose config` when Docker exists; otherwise mark BLOCKED, not PASS.
5. Specify safe future SQL install order without rerunning destructive fresh-DB Day 1 bootstrap. Do **not** create a new schema table to solve idempotency automatically.

**Tests/evidence:** existing matching regression, event contract tests, `python -m pytest -m day1 -q` when DB ready, `docker compose config`/health when available; compare actual 13-table names and ER relationships.

**Gate:** Contract version recorded, original service stack reproducible or explicitly blocked, no ER mutation, no frontend edits. **STOP: PLANNED HUMAN REVIEW #1.**

### Phase 2 — Independently prove ACID reservation and in-memory matching/analytics (original Day 2 correctness core)

**Allowed files:** `db/procedures/place_and_reserve_order.sql` (preserve correct logic; only repair demonstrated defects), `backend/matching/order_book.py` (minimal changes only), `backend/matching/fenwick.py`, `backend/matching/rolling_vwap.py`, `backend/matching/reference_matcher.py` (only if moving the existing independent oracle without deleting tests), `backend/matching/engine.py` (pure single-writer wrapper), `tests/concurrency/test_reservation.py`, `tests/concurrency/test_double_spend.py`, `tests/unit/test_matching_engine.py`, `tests/unit/test_matching.py`, `tests/unit/test_fenwick.py`, `tests/unit/test_rolling_vwap.py`, `scripts/verify_schema.py` (non-destructive checks only). New file `scripts/setup_backend.sh` may be created **inside the existing scripts folder** for incremental SQL installation; add `.env.example` only if essential.

**Why these choices:**

- PostgreSQL `SELECT ... FOR UPDATE` creates the one serialized account-reservation boundary, protecting the `cash -> escrow` transition from double spend; if the transaction aborts both the order insert and money movement roll back.
- The existing book uses **dict price→doubly linked FIFO** for arrival priority at a price; **dict order_id→node** for O(1) expected cancellation; and min/max heaps of price levels (O(log P) when introducing a level). Matching occurs at the resting maker price and uses integer ticks. Keep the independent brute-force differential test, which is more compelling than just unit examples.
- The original also requires a **Fenwick Tree (Binary Indexed Tree)** for O(log M) volume updates/range sums and an actual **cumulative-prefix circular buffer** for O(1) rolling VWAP. Implement both as isolated in-memory algorithms and test against naive scan references. Choose a documented finite tick-bucket universe or a tested dynamic expansion strategy: arbitrary sparse BIGINT ticks cannot just be fed directly into a small Fenwick array.

**Codex steps:**

1. Inspect the existing reservation SQL and run the real concurrency tests *after* installing the function safely into a local initialized DB. Never run `setup_day1.sh` on a database with existing tables. `setup_backend.sh` should be incremental, re-runnable, transactional where possible and must not erase seeded accounts.
2. Confirm lock scope, big integer overflow, fee rounding, active instrument checks, lot-size checks and privilege restrictions. Ensure two simultaneous orders that compete for one margin balance cannot both succeed.
3. Review and preserve `OrderBook.submit`, `cancel`, `depth`, its self-trade policy, FIFO, lazy heap deletion and invariant checker. Re-run all 4×2,000 randomized differential tests; do not reimplement the book without evidence.
4. Implement `backend/matching/fenwick.py` with `point_add(i, delta)`, `prefix_sum(i)`, `range_sum(l,r)` or equivalent; maintain per-instrument volume **of trades/executions**, not of merely resting orders. Keep statistics updates out of SQL and book matching I/O; later phases will feed settled fills.
5. Implement `backend/matching/rolling_vwap.py` as a **true fixed-size prefix-sum ring**. Store cumulative `Σ(price × qty)` and `Σqty`, derive the N-event window by prefix subtraction, correctly handle wraparound/evictions; display averages using Decimal or rational output, not money floats. Distinguish this from the *SQL 10-minute rolling VWAP* of Day 4.
6. Establish one-writer orchestration in `backend/matching/engine.py` **without** any real DB or network call yet. Its pure-book functions must remain deterministically testable.
7. Add and run tests: price/time priority, partial fill, cancel, self-trade prevention, cross-instrument separation, BIT boundaries/negative rejection/dynamic bucket handling, VWAP first/last/wraparound, race 2/8 concurrent order requests, rollback and overflow.

**Gate:** Independently passing risk reservation and matching/analytics tests; no API integration or settlement claimed yet. **RECORD PHASE PASS AND ADVANCE AUTOMATICALLY within authorized Batch B; stop only for a documented exception blocker.**

### Phase 3 — FastAPI gateway and role-scoped login, Tier 2→Tier 3 wiring (original Day 3)

**Allowed files:** `backend/api/main.py`, `backend/api/dependencies.py`, `backend/api/routes/auth.py`, `backend/api/routes/orders.py`, `backend/api/routes/market.py`, `backend/api/routes/admin.py`, `backend/auth/security.py`, `backend/auth/rbac.py`, `backend/stores/postgres.py`, `backend/risk/order_reservation.py`, `backend/matching/engine.py`, `backend/events/dispatcher.py`, `backend/events/trade_event.py`, `backend/config.py`, `requirements.txt`, `.env.example`, `scripts/setup_backend.sh`, `tests/integration/test_order_pipeline.py`, `tests/integration/test_rbac.py`. Any additional file proposed under an existing directory must be disclosed before editing.

**Codex steps:**

1. Implement FastAPI startup, health and request validation using configured dependencies. Single in-memory book owner; run **one Uvicorn worker**. OpenAPI is a backend contract, not a UI.
2. Implement `POST /login`: bcrypt verification against `user_account`, short-lived signed JWT with `sub`, `role`, issue/expiry times. Do not return hashes. Trade routes resolve trader from JWT, not caller-supplied trader UUID. Protect admin-only routes at API and PostgreSQL boundaries.
3. Implement least-privileged runtime PostgreSQL DB identity and allowed `GRANT`/`REVOKE` for reservation routines. Set `SET LOCAL app.role` inside the same DB transaction as policy-restricted queries; never use `SET LOCAL` alone to impersonate an actual role. Verify RLS with effective DB role, not the Day 1 administrator user.
4. Wire authenticated order request → SQL `place_and_reserve_order()` → **COMMIT** → `OrderBook.submit`. Use its `Fill` objects to construct immutable trade events. The event dispatcher is wired in contract form but **do not report fills as financially settled yet**; settlement comes in Phase 4. Query/open-order routes may work; cancellation may explicitly respond 501 until safe SQL cancellation is implemented in Phase 4.
5. Ensure `OrderBook` itself performs no SQL or network I/O, and that an unavailable downstream worker cannot silently drop events. If an event queue has finite capacity, check/reserve dispatch capacity *before* mutating the book or fail closed. Document crash window and do not claim durable delivery.
6. Implement the source-prescribed `GROUP BY ... HAVING` demonstration in `db/queries/price_band_having.sql` (allowed extra existing placeholder) and prove it on seeded executions once available; at this phase it may be syntactically verified if settlement data is absent.
7. Test authenticated/trader/admin login, JWT expiry/wrong-role, forged trader identity, RLS and grants, accepted order in DB + matching engine, rejected order never reaches engine, deterministic event emission, concurrent request ordering. Do not fake settlement success.

**Gate:** Authenticated API accepts a risk-approved order and emits deterministic match events only *after* SQL commit; no frontend or settlement pretending. **RECORD PHASE PASS AND ADVANCE AUTOMATICALLY within authorized Batch B; stop only for a documented exception blocker.**

### Phase 4 — ACID settlement, positions and PnL, cancellation and event fan-out (original Day 4 correctness system-of-record)

**Allowed files:** `db/procedures/settle_execution.sql`, `db/triggers/update_positions.sql`, `backend/clearing/settlement.py`, `backend/workers/settlement_worker.py`, `backend/events/dispatcher.py`, `backend/api/routes/orders.py`, `backend/stores/postgres.py`, `backend/matching/engine.py` (integration only), `tests/concurrency/test_settlement_locks.py`, `tests/integration/test_order_pipeline.py`, `tests/integration/test_database_integrity.py`, `tests/concurrency/test_reservation.py`, `scripts/setup_backend.sh`. A **new** `db/procedures/cancel_order.sql` is allowed only within the existing `db/procedures/` directory and must be justified by the existing order lifecycle; no new table, foreign key or ER entity.

**Codex steps:**

1. Before generating settlement code, show and have the human approve a worked **two-trader financial ledger** for BUY and collateralized SELL: starting cash/escrow, reservation, partial fill at maker price, actual maker/taker fees, fee budget/rounding across partitions, remaining escrow, cancellation and final balances. Use `Decimal`/integer exact arithmetic. **Do not proceed if partitioned fees can exceed reserve.** Treat order fee-tier changes while OPEN/PARTIAL as prohibited until a schema-compatible policy is agreed. This is an accounting decision required to faithfully implement the source's ACID claim, not an authorization to add a 14th table.
2. Implement `settle_execution()` that consumes a stable execution identifier and immutable fill identity; checks buy/sell order IDs, counterparty ownership, same instrument, opposite sides, correct tick/lot, remaining quantities, maker pricing and non-self-trade. **Duplicate same ID/same payload:** no money moves. **Duplicate same ID/different payload:** reject. The existing `execution.id` can be allocated prior to the worker; no new execution-ID table.
3. Lock account rows in **ascending trader UUID order** as the original promises. Globally consistent order-row locks and cancellation locks prevent creating another lock-order inversion. Revalidate financial state under locks; never depend only on the earlier API risk check.
4. In the same PostgreSQL transaction, insert `execution`, adjust both account cash/escrow, update `"order".filled_quantity/status`, and let the AFTER INSERT trigger update positions. Reject overflow, negative escrow and insufficient committed collateral. Buyer gets limit-price improvement refund; seller gets sale proceeds and releases collateral; fees are accounted once.
5. Implement `db/triggers/update_positions.sql` for affected `(trader,instrument)` on execution insertion. The frozen `position` schema has no average entry-price field. Compute gross realized PnL from historical executed prices with a documented weighted-average cost method; handle long, short, partial close, flat and sign-flip; label gross PnL as excluding fees. Explain that recomputation cost increases with history and cannot be called O(1).
6. Implement cancellation of OPEN/PARTIAL residuals with authorization, single release of remaining escrow, order-book cancellation and consistent DB state. Resolve races between fill, cancel and archive. A fully FILLED order cannot be cancelled. Self-trade prevention must release the incoming residual without discarding already legitimate fills.
7. Worker ordering: settlement worker consumes raw fills and commits first; only **after** successful commit may Redis/Neo4j/vector consumers receive settled events. Failed settlement makes service unhealthy/fail-closed; it cannot be silently retried with a *different* event identifier. Explain limitations of an in-memory-only queue; do not claim crash recovery is solved by this phase.
8. Test actual PostgreSQL concurrency with two-account opposite-direction settlements; replay, rollback, partial fill/cancel, partitioned fee rounding, fee tiers, maker price improvement, total `cash+escrow` conservation net of fees, positions/PnL, and exactly one `execution` per fill ID. Test no phantom settlement status is returned before commit.

**Gate:** End-to-end two real API traders can reserve→match→settle; order status/escrow/position/PnL are correct; verified idempotency and concurrent locking. If original no-money-loss durability cannot be demonstrated with the frozen ER/event pipeline, label that proof **BLOCKED / not claimed**, and ask for approval rather than inventing a ledger. **RECORD PHASE PASS AND ADVANCE AUTOMATICALLY within authorized Batch B; stop only for a documented exception blocker.**

### Phase 5 — Complete PostgreSQL advanced SQL and archival (original Day 4 + Unit 2/3 syllabus)

**Allowed files:** existing placeholders `db/queries/order_archive.sql`, `db/queries/price_band_having.sql`, `db/queries/recursive_desk_rollup.sql`, `db/queries/rolling_vwap.sql`, `db/queries/set_operations.sql`, `db/queries/full_text_search.sql`, `db/queries/vector_similarity.sql`, `db/views/order_book_view.sql`; `backend/stores/postgres.py`, `backend/api/routes/admin.py` for read endpoints; `scripts/setup_backend.sh`; existing integration tests. New document under **existing** `docs/architecture/` e.g. `docs/architecture/query-optimization.md` is allowed.

**Codex steps:**

1. Implement `order_book_view` over SQL OPEN/PARTIAL orders; do not claim it is the hot-path book. Verify aggregate remaining quantity by instrument/side/price.
2. Implement atomic order archival `DELETE ... RETURNING` + `INSERT INTO order_history`, preserving original ID and retaining data needed for `execution` references. Archive only terminal, fully accounted orders. Test INSERT/DELETE/SELECT and idempotent rerun.
3. Implement `recursive_desk_rollup.sql` traversing self-referential `desk.parent_desk_id` with cycle protection; aggregate both position realized PnL and relevant execution volume, verifying seed hierarchy. Explain difference between recursive CTE and a fixed join depth.
4. Implement `price_band_having.sql` (`GROUP BY ... HAVING`), SQL rolling 10-minute VWAP with **window functions**, set operations (`INTERSECT`/`EXCEPT`) for maker/taker classification, plus *both* nested and correlated subquery demonstrations required by the source's Unit 2 mapping. No new SQL directory: place clearly labelled query sections in the existing `db/queries/` files; document where each runs.
5. Preserve existing `market_disclosure` generated `body_tsv` GIN index and `regime_snapshot VECTOR(6)` HNSW; write their source-promised parameterized query SQL even if live feature generation will be completed Phase 8.
6. Capture actual `EXPLAIN (ANALYZE, BUFFERS)` on seeded representative datasets for sequential/B-tree/BRIN/covering-index approaches and compare to Fenwick price-band reads (time each in its own context). Add compatible indexes only where necessary with safe incremental SQL; do not insert a new DB table. Explain index choice/selectivity, filter costs, correlation and whether the planner actually uses each index. Never invent speedup factors.
7. Execute each query and compare expected rows; test join correctness, window frames, HAVING threshold, archival integrity, set ops, nested/correlated outputs, recursive rollups and RLS restrictions.

**Gate:** Every required advanced SQL example is executable and documented with real query output or a clearly labelled future-data prerequisite; actual optimizer plans stored. **RECORD PHASE PASS AND ADVANCE AUTOMATICALLY within authorized Batch B; stop only for a documented exception blocker.**

### Phase 6 — Redis key-value L2 depth (original Day 5 first derived store)

**Allowed files:** `backend/stores/redis_depth.py`, `backend/workers/cache_worker.py`, `backend/events/dispatcher.py` (routing only), `backend/api/routes/market.py`, `tests/integration/test_polyglot.py`, `.env.example`, `requirements.txt`, `docker-compose.yml` (service adjustments only).

**Why Redis:** live top-20 bids/asks should be read quickly without scanning the PostgreSQL order table; Redis is derived and rebuildable and never decides money or matching. Top-20 depth must be **sorted by price**.

**Codex steps:**

1. Use the source's key family `depth:{symbol}:bids` and `depth:{symbol}:asks`. The original reference's example `score=quantity` plus `ZREVRANGE` is incompatible with price-time best-bid ordering; **correct this implementation-level bug while preserving intent**. Use a price-ordered sorted-set and, if needed, a companion quantity hash within the existing key family. If scoring ticks as a Redis float, test and document the 2^53 exact-integer limit; alternatively use lexicographic fixed-width encoding. Do not silently narrow SQL BIGINT columns.
2. On every book mutation (submit, full/partial fill, cancellation), publish ordered book-depth updates from a coordinator *outside* the matching hot path. Prevent stale snapshots overwriting newer versions. Aggregate at price level; read top 20 bids descending and asks ascending.
3. Demonstrate `ZADD`/`HSET` creation, level updates, `ZREM`/`HDEL` empty-level removal and `DEL` when appropriate. Redis is **not** the authoritative order source.
4. Expose a backend market-depth route that reads actual Redis results (with stale/unavailable status honest), and compare output to `OrderBook.depth()` across 21+ price levels and several symbols.
5. Test Redis service outage and recovery/rebuild; matching and PostgreSQL funds remain unaffected by cache downtime. Do not claim sub-millisecond without actual timed evidence.

**Gate:** Redis top-20 price ladder agrees with authoritative in-memory book after every tested mutation; create/update/delete demonstrated. **RECORD PHASE PASS AND ADVANCE AUTOMATICALLY within authorized Batch B; stop only for a documented exception blocker.**

### Phase 7 — Neo4j counterparty graph and ring detection (original Day 5 second derived store)

**Allowed files:** `backend/stores/neo4j_graph.py`, `backend/workers/graph_worker.py`, `db/neo4j/constraints.cypher`, `db/neo4j/seed.cypher`, `db/neo4j/wash_trade_cycles.cypher`, `db/neo4j/retention.cypher`, `backend/events/dispatcher.py` (post-settlement routing), `backend/api/routes/admin.py`, `tests/integration/test_polyglot.py`, `docker-compose.yml` (service settings only).

**Why graph:** Cypher traverses a variable-length closed directed counterparty ring A→B→C→A without long chains of SQL self-joins. A ring is a *surveillance candidate*, not proof of manipulation.

**Codex steps:**

1. Connect via env, create unique `Trader.id` constraint; preserve **only** `(:Trader)` nodes and `[:EXECUTED_AGAINST]` directed weighted edges from the source. No unapproved `ProcessedExecution` node or new graph schema.
2. On distinct committed PostgreSQL executions, `MERGE` endpoints and relationship, `ON CREATE` initialize count/notional/time and `ON MATCH SET` increment for a **new trade only**. Explain why naive replay increments twice; implement a replay-safe reconciliation path that computes authoritative aggregate counts from Postgres for rebuilds (and test it).
3. Seed one demonstrable 3-trader ring and implement Cypher cycle search of length 3..5 with bounded results and no misleading claim of confirmed wrongdoing.
4. Implement stale-edge retention DELETE with `last_traded_at` and test it preserves fresh edges. Ensure archive/history does not accidentally remove execution facts required for rebuilding Neo4j.
5. Expose admin-only API read route; assert trader forbidden with JWT and relevant database grants.

**Gate:** weighted edge updates, repeated distinct trades, seeded ring, graph retention and replay/rebuild correctness observable via actual Cypher. **RECORD PHASE PASS AND ADVANCE AUTOMATICALLY within authorized Batch B; stop only for a documented exception blocker.**

### Phase 8 — Six-dimensional pgvector, FTS and normalization proof (original Day 6)

**Allowed files:** `backend/stores/regimes.py`, `backend/workers/regime_worker.py`, `backend/api/routes/admin.py`, `db/queries/vector_similarity.sql`, `db/queries/full_text_search.sql`, `tests/integration/test_polyglot.py`, `tests/integration/test_rbac.py`; new `docs/architecture/polyglot-data-models.md` and `docs/architecture/normalization-proof.md` within existing directory.

**Why vector and FTS:** vector distance finds historical microstructure patterns similar to current market conditions; FTS finds keywords in disclosures. Each uses PostgreSQL because the structured metadata and role policies already live there.

**Codex steps:**

1. Derive a per-instrument, per-interval **6-feature numeric vector** strictly in source order: `[spread, order_book_imbalance, vwap_drift, trade_velocity, depth_ratio, realized_volatility]`. Document units, normalization and zero/missing data handling, and why these are hand-engineered features **not transformer embeddings**.
2. Store in the existing `regime_snapshot.features VECTOR(6)` table; use `INSERT ... ON CONFLICT(instrument_id,captured_at) DO UPDATE` while an interval forms; delete snapshots older than a documented retention period. Do not add vector tables.
3. Execute cosine nearest-neighbor retrieval `ORDER BY features <=> query_vector LIMIT k` with an optional instrument filter; show real ranked results and exact matching on a controlled seeded case. Explain approximate HNSW, and don't claim it always beats a seq scan for tiny datasets.
4. Load clearly synthetic disclosures into the existing `market_disclosure` schema and query using generated `body_tsv`/GIN. Show indexed full-text search with nonempty ranked result sets.
5. Use PostgreSQL native `compliance_admin_role`, forced RLS and `SET LOCAL app.role` with effective least-privileged DB role. Show both tables are inaccessible to a trader directly and via protected API; distinguish backend auth from role spoofing.
6. Create full worked normalization evidence for the **existing schema**: candidate keys and FDs, Armstrong's inference/attribute closure, a hypothetical denormalized `TRADER_DESK_ASSIGNMENTS` BCNF issue and correction reflected in `desk.manager_trader_id`; independent multivalued dependencies in a hypothetical combined margin/position relation and 4NF decomposition. Explain why no production table is actually being added or falsely declared non-BCNF. Include 1NF → 2NF → 3NF → BCNF → 4NF steps.
7. Document Redis exact key representation, Neo4j nodes/edges, pgvector dimensions/metric/index/retrieval/retention, cross-store authority and consistency; test vector UPSERT/DELETE, FTS, RLS and full-text input safety.

**Gate:** actual pgvector/FTS results, administrator-only DB/API access, detailed normalization proof and cross-store data-model documentation. **RECORD PHASE PASS AND ADVANCE AUTOMATICALLY within authorized Batch B; stop only for a documented exception blocker.**

### Phase 9 — Deterministic market simulator and complete backend integration (original Day 8 integration subset)

**Allowed files:** `backend/simulator/market_simulator.py`, `scripts/run_simulation.py`, `backend/events/dispatcher.py`, existing worker files, `backend/api/main.py` and route modules (integration fixes only), `tests/integration/test_order_pipeline.py`, `tests/integration/test_polyglot.py`, `tests/concurrency/test_double_spend.py`, `tests/concurrency/test_settlement_locks.py`, `scripts/setup_backend.sh`.

**Codex steps:**

1. Build deterministic synthetic multi-instrument trades with seed; exercise BUY/SELL, maker price, FIFO, partial fill, cancellation, simultaneous reservations, role separation, overflow rejection and failed/duplicate settlement. Demo data must be isolated; never indiscriminately truncate existing user databases.
2. Demonstrate a full sequence: login → reserve/commit → match → enqueue/settle/commit → position/PnL → Redis depth → Neo4j weighted ring → vector upsert/similarity → disclosure FTS → advanced SQL results. Poll async materialization **with bounded timeout**, never arbitrary sleeps and never fake success.
3. Verify original `execution`, `order`, `position`, `margin_account` and archive data against expected cash/quantity/fee conservation; ensure graph and vector only reflect authoritative PostgreSQL executions.
4. Repeat a fill with the *same* event ID; assert no extra money moves and no graph double-count. Replay a *different* payload under same ID; assert conflict. Test slow/down derived store doesn't block the synchronous matching function or corrupt cash.
5. Exercise accounts and routes for both roles; enforce RLS on admin vector/disclosure reads, and present exact SQL/Cypher/Redis outputs.
6. Document the bounded demo model: no frontend, no claim of production-grade crash recovery, no unmeasured microsecond guarantee; identify any unmet original correctness proof explicitly.

**Gate:** all four backend tiers and all data stores observable from an automated seeded scenario with real services. **RECORD PHASE PASS AND ADVANCE AUTOMATICALLY within authorized Batch B; stop only for a documented exception blocker.**

### Phase 10 — Optimization benchmarks and latency-isolation tests (original Step 8 verification)

**Allowed files:** `tests/benchmarks/test_matching_latency.py`, `tests/benchmarks/test_latency_isolation.py`, existing unit/integration/concurrency tests (fix only proven defects), and `docs/architecture/query-optimization.md`.

**Codex steps:**

1. Benchmark operations separately: `OrderBook.submit`, matching fills, known-node cancellation, depth snapshots, Fenwick range queries, rolling VWAP. Report sample count, warmup, Python version/hardware, median/p95/p99. No invented or guaranteed microsecond results.
2. Run independent brute-force differential tests with multiple seeds; compare all fills, remaining quantities, FIFO and depth snapshots after cancels; do not use the optimized book as its own oracle.
3. Measure Fenwick vs direct O(M) scan and ring-buffer VWAP vs O(N) historical re-scan at representative sizes; correctness first, performance second.
4. Deliberately slow a Tier 4 worker (graph/vector) and compare *isolated matching core* latency to baseline; also report end-to-end event-settlement latency separately. The original statement is **no slow downstream query may directly block the matcher**; verify architecture-level separation, not a statistically implausible identical run time.
5. Re-run optimizer lab query comparisons: seq/B-tree/BRIN/covering `EXPLAIN ANALYZE`, plus Python in-memory price band. Explain if PostgreSQL's optimizer chooses different plans than expected.
6. Execute `python -m pytest -q` with actual services and record PASS/FAIL/BLOCKED. If a service is missing, do not count those tests as passed. Confirm `scripts/verify_schema.py` sees exactly 13 tables.

**Gate:** reproducible correctness, measured efficiency and measured downstream isolation without false performance claims. **RECORD PHASE PASS AND ADVANCE AUTOMATICALLY within authorized Batch B; stop only for a documented exception blocker.**

### Phase 11 — Backend documentation, rubric traceability and final user handoff

**Allowed files:** `README.md` (truthful backend status and local setup only), `.env.example` (safe placeholders), `docs/architecture/backend-contracts.md`, `docs/architecture/polyglot-data-models.md`, `docs/architecture/query-optimization.md`, `docs/architecture/normalization-proof.md`; new `docs/architecture/backend-demo.md` inside existing directory. `tests/` and `scripts/` may be corrected only for proven setup defects.

**Codex steps:**

1. Write exact runbook: fresh or existing DB safe setup, startup order for pgvector/Postgres/Redis/Neo4j, application API and worker(s), seed/demo, test commands, cleanup of synthetic data only. No hardcoded secrets.
2. Document ER entity/table/PK/FK/constraints and relational reduction, 13-table data dictionary, why each storage technology is appropriate, Redis keys, Cypher model, vector feature definition, roles and RLS.
3. Present executable query catalog: DDL/ALTER/DROP, INSERT/UPDATE/DELETE/SELECT, joins, aggregations/HAVING, nested + correlated subqueries, set operations, recursive CTE, window VWAP, views, stored functions, trigger, full-text, HNSW, EXPLAIN plans.
4. Include actual verification evidence with exact commands and results, representative terminal/JSON/Cypher/SQL outputs, measured latency tables, failure/blocked status, and limitations. Explain the original Day 7–8 UI and recorded user demonstration remain **future frontend tasks**; do not claim they are finished.
5. End with a rubric traceability matrix and a list of outstanding source requirements; include contributor/change-log guidance, but **do not stage, commit or push** on the user's behalf.

**Gate:** All required backend deliverables linked to source and runnable evidence, no fake completeness, `frontend/` untouched, user receives exact changed-file/test/diff summary. **STOP: PLANNED HUMAN REVIEW #2.**

---

## 7. Exact file-location policy and phase ownership

**Do not rearrange project directories.** Use these pre-existing paths for implementation. “New” means the file name is proposed *inside an existing directory*, not a new subproject.

| Responsibility | Existing directory / exact files | Phase |
|---|---|---|
| Backend settings | `backend/config.py`, `.env.example`, `requirements.txt` | 1 |
| Domain event types | `backend/events/trade_event.py` | 1 |
| ACID settlement and clearing | `db/procedures/settle_execution.sql`, `backend/clearing/settlement.py` | 4 |
| Position trigger | `db/triggers/update_positions.sql` | 4 |
| Incremental SQL install | `scripts/setup_backend.sh` **(new inside existing scripts dir)** | 2–4 |
| Reservation and cancellation | `db/procedures/place_and_reserve_order.sql`, optional `db/procedures/cancel_order.sql` **(new inside existing procedures dir)**, `backend/risk/order_reservation.py` | 2–4 |
| FastAPI app and dependency injection | `backend/api/main.py`, `backend/api/dependencies.py` | 3 |
| Role-scoped JWT | `backend/auth/security.py`, `backend/auth/rbac.py`, `backend/api/routes/auth.py` | 3 |
| Orders and market endpoints | `backend/api/routes/orders.py`, `backend/api/routes/market.py` | 3–4 |
| Admin endpoints | `backend/api/routes/admin.py` | 3, 5, 7–8 |
| PostgreSQL client adapter | `backend/stores/postgres.py` | 3 |
| Core matching and dispatch | `backend/matching/order_book.py` (preserve), `backend/matching/engine.py`, `backend/events/dispatcher.py` | 2–4 |
| Algorithms | `backend/matching/fenwick.py`, `backend/matching/rolling_vwap.py`, `backend/matching/reference_matcher.py` | 2 |
| Settlement worker | `backend/workers/settlement_worker.py` | 4 |
| SQL teaching artifacts | `db/views/order_book_view.sql`, all existing `db/queries/*.sql` | 5 |
| Redis depth and worker | `backend/stores/redis_depth.py`, `backend/workers/cache_worker.py` | 6 |
| Neo4j and worker | `backend/stores/neo4j_graph.py`, `backend/workers/graph_worker.py`, existing `db/neo4j/*.cypher` | 7 |
| Market regimes and worker | `backend/stores/regimes.py`, `backend/workers/regime_worker.py` | 8 |
| Local service orchestration | required source-planned root `docker-compose.yml` (no new directory) | 1 |
| Market simulator | `backend/simulator/market_simulator.py`, `scripts/run_simulation.py` | 9 |
| Matching unit tests | existing `tests/unit/test_matching_engine.py`, `test_order_book.py`, `test_matching.py`, `test_fenwick.py`, `test_rolling_vwap.py` | 2, 10 |
| DB concurrency tests | existing `tests/concurrency/test_reservation.py`, `test_double_spend.py`, `test_settlement_locks.py` | 2, 4, 9 |
| Integration tests | existing `tests/integration/test_database_integrity.py`, `test_rbac.py`, `test_order_pipeline.py`, `test_polyglot.py` | 2–10 |
| Benchmark tests | existing `tests/benchmarks/test_matching_latency.py`, `test_latency_isolation.py` | 10 |
| ER/design documentation | preserve `docs/er/tradegraph-er.md`, `docs/architecture/day1-decisions.md`; new docs **within `docs/architecture/` only** | 1, 5, 8, 11 |
| Frontend | `frontend/**` | **Never touch this sprint** |

**New-file approval rule:** Before creating a file, Codex must say why an existing placeholder cannot hold that code. Then create it in the correct existing directory. The only planned root-level addition is `docker-compose.yml`. Use no `src/` rewrite, no `services/` directory, no new `packages/`, no new `migrations/`, and no other root-level additions without user approval. Reuse existing `.py`, `.sql` and `.cypher` placeholders aggressively rather than generating duplicate implementations.

### Existing `__init__.py` placeholders

Empty `backend/__init__.py` and `backend/api/__init__.py` are valid Python package markers; **do not fill them merely to eliminate empty files**. The target is functional coverage, not eliminating every zero-byte tracked file.

---

## 8. Traceability to DBMS Level 3 requirements

Every requirement needs **source code + reproducible evidence**, not just a line in README. The course requirement is SQL (PostgreSQL/MySQL) plus NoSQL **or** vector, at least four advanced SQL concepts and at least one NoSQL/vector, appropriate integrity/security, Next.js web interface and documentation. This **backend-only sprint** completes backend evidence; Next.js compliance remains outstanding until a separate frontend sprint.

| Course concept | TradeGraph evidence to produce | Test / demonstration |
|---|---|---|
| Meaningful non-CRUD problem | Exchange matching, ACID risk guard, clearing, surveillance | Two-party crossing order scenario |
| ER model / relational reduction | `docs/er/tradegraph-er.md`, schema, data dictionary | Exactly 13 tables; PK/FK integrity tests |
| CREATE / ALTER / DROP | `db/schema.sql` | Setup + schema verifier |
| INSERT / UPDATE / DELETE / SELECT | Order reserve, execute, archive and query | Show live rows change and old rows archive |
| JOINS / aggregates / GROUP BY / HAVING | `db/queries/price_band_having.sql` and API | Seeded expected grouped values |
| Views | `db/views/order_book_view.sql` | Query result for active orders |
| Stored procedures/functions | Reservation, settlement, cancellation | Test atomic effects and rollback |
| Triggers | `db/triggers/update_positions.sql` | Automatic position/PnL update |
| Transactions + concurrency | `FOR UPDATE`, ascending account locks | Double-spend and settlement races |
| Recursive queries | `db/queries/recursive_desk_rollup.sql` | Hierarchical desk totals |
| Window functions | `db/queries/rolling_vwap.sql` | 10-minute VWAP on historical executions |
| Set operations / subqueries | `set_operations.sql`, additional named SQL in existing query files if needed | Verify mathematically expected membership |
| Indexing and optimizer | B-Tree, GIN, HNSW, `EXPLAIN ANALYZE` | Query plans before/after; no fabricated results |
| Full-text search | Generated `body_tsv`, GIN and search query | Relevant disclosures returned |
| NoSQL key-value | Redis sorted depth cache | top-20 + eviction correctness |
| NoSQL graph | Neo4j counterparty edges and Cypher cycles | seeded 3-trader cycle + edge update/delete |
| Vector database | pgvector `VECTOR(6)` + cosine HNSW | upsert/search/retention with true synthetic features |
| Security/RBAC | bcrypt/JWT, runtime PG privileges, RLS | trader denied admin data; admin succeeds |
| Polyglot data model justification | `docs/architecture/polyglot-data-models.md` | Explain authority, keys/nodes/vectors/retrieval |
| Functional Next.js interface | **Separate future sprint** | Must not be marked completed here |
| Final documentation/report | backend docs, test logs, ER proofs, screenshots later | Backend evidence, then future UI report integration |

Four advanced SQL concepts are already exceeded if transactions, views, triggers, stored routines, indexing, CTE/window functions and FTS actually work. Neo4j/Redis/pgvector each supply additional domain-aligned persistence paradigms instead of decorative installations.

---

## 9. Integration checkpoints and acceptance evidence

For the final backend demonstration, produce one **deterministic evidence ledger** in `docs/architecture/backend-demo.md`:

1. **DB identity/schema:** query shows exactly 13 physical tables; correct FK/PK constraints; role/RLS metadata; pgvector installed; no extra table.
2. **Risk race:** two concurrent incoming orders targeting insufficient shared funds yield the expected accepted/rejected count; balances never negative.
3. **End-to-end fill:** Alice submits resting BUY; Bob submits crossing SELL; execution uses maker price; orders and escrow/positions all agree.
4. **Partial fill/cancel:** residual quantity can be canceled, returns its correct fee-inclusive reserve, and is removed from in-memory/Redis depth.
5. **Execution replay:** same immutable event ID applied twice creates one `execution` and one net financial effect; conflicting payload with same ID rejected.
6. **Position accounting:** long close, short cover and flip result in expected net position and gross realized PnL; cash fees accounted separately.
7. **Fenwick/VWAP:** exact equality with independently calculated quantities and weighted sums on seeded events.
8. **Redis:** best bids/asks sorted by **price**, quantity aggregated, empty price removed, snapshot equals in-memory book.
9. **Neo4j:** weighted edge update, replay dedupe, seeded 3-node loop found, stale edge deleted.
10. **pgvector:** generated six-feature snapshot stored, forming interval upserted, nearest matches returned, old snapshots deleted.
11. **FTS:** disclosure search finds seeded content through GIN-capable query; trader blocked by RLS and API.
12. **SQL optimizer:** actual query plans and timings with dataset size, planner note and baseline; no unsupported performance claim.
13. **Latency isolation:** deliberately slow graph/vector worker changes downstream completion time but not isolated order-book operation's execution distribution beyond measured variability; report both measurements.
14. **Security:** JWT expiry, role separation, forged trader identity, SQL privilege and RLS tested.
15. **Negative cases:** inactive instrument, bad lot, insufficient funds, invalid price/quantity, self-trade and duplicate request explicitly rejected without corrupting financial state.

### Mandatory validation commands (from the project root)

```bash
# Preserve existing matching correctness throughout:
python -m pytest tests/unit/test_matching_engine.py -q

# Unit algorithms and data structure invariants:
python -m pytest tests/unit -q

# PostgreSQL baseline (when a populated local DB is configured):
python scripts/verify_schema.py
python -m pytest -m day1 -q
python -m pytest tests/concurrency/test_reservation.py -q

# After settlement and API phases:
python -m pytest tests/concurrency tests/integration -q

# After all backends and services are up:
python -m pytest -q
python scripts/run_simulation.py
```

`pytest.ini` must register any new custom markers and make them meaningful. Do not skip a missing integration dependency while reporting an all-green backend; record it as blocked and show why. A clean unit-only run and a blocked polyglot run are different results.

### User-approved commit process (Codex must NOT do this)

At each of the two planned review checkpoints (or an exception stop), the human can review locally:

```bash
git status --short
git diff --stat
git diff --check
# run phase test commands shown in the Codex handoff
# Then the human reviews, stages, commits, and pushes as desired.
```

Codex must not invoke any of the subsequent staging/commit/push commands. If tests fail, provide a specific bug diagnosis and propose fixes **within the same phase**, not by loosening tests.

### Required Codex phase handoff template

```text
PHASE: N — <name>
RESULT: PASS / FAIL / BLOCKED
LOCAL REPOSITORY: <absolute path>  BRANCH: <branch>
FILES MODIFIED: <exact paths>
FILES CREATED: <exact paths, with why they fit existing structure>
DB OBJECTS CHANGED: <functions, views, triggers, indexes, grants>
CONTRACTS CHANGED: <none / approved specific change>
13-TABLE ER PRESERVED: YES / NO (if NO, STOP)
FRONTEND UNTOUCHED: YES / NO
IMPLEMENTED FEATURES: <observable behavior>
TEST COMMANDS + RESULTS: <exact commands, passed/failed/skipped counts>
RUNTIME EVIDENCE: <actual sample data or API/SQL/Cypher output>
KNOWN LIMITATIONS: <specific, honest>
GIT DIFF --STAT: <output>
GIT STATUS --SHORT: <output>
NEXT PHASE READY: YES / NO
COMMIT PERFORMED: NO
PUSH PERFORMED: NO
GATE DECISION: AUTO-ADVANCED / PLANNED REVIEW #1 / PLANNED REVIEW #2 / EXCEPTION STOP
```

---

## 10. Risk register: high-probability blockers in a one-Codex 24-hour sprint

| Risk | Why it is likely | Required mitigation |
|---|---|---|
| Existing DB has only Day 1 SQL installed | Reservation function stored in separate SQL file, and fresh setup rejects populated schemas | Read-only catalog check; safe incremental `scripts/setup_backend.sh` |
| Settlement money/escrow mismatches | Partial-fill rounding, separate buyer/seller policy, pooled escrow | Freeze `R(q)` formula, table-driven accounting tests, rollback/replay tests |
| `execution` schema has no replay UUID and no fee ledger | Frozen ER deliberately has only BIGSERIAL execution ID | Stable execution ID, idempotent SQL function, explicit limitations |
| Event queue not crash-durable | No outbox/event-log SQL table permitted | Nonblocking demo queue + fail-closed state; document recovery limitation |
| Neo4j retries duplicate weights | MERGE on relationship does not dedupe events by itself | Authoritative PostgreSQL aggregate reconciliation; no extra graph entity without approval |
| Redis ZSET sorts by wrong key | Source plan's score-as-quantity example conflicts with best-price ordering | Score by price; HASH quantity; test 21+ levels |
| PnL lacks stored cost basis | Current `position` has no cost-basis field | Historical weighted-average recomputation in trigger; disclose complexity |
| Concurrent web workers split books | One in-memory book per Uvicorn worker | Document/run `--workers 1`, single serialized engine owner |
| RLS bypass / role spoof | Superusers bypass RLS; `app.role` alone is not trusted | Separate runtime DB role + GRANT/RLS tests + JWT-to-trader mapping |
| SQL demo may show seq scan over HNSW/GIN | Tiny datasets and planner selectivity | Honest EXPLAIN with realistic samples; never invent index speedups |
| Graph cycles mistaken for illegal trades | Closed ring alone isn't proof of wash trading | Label as suspicious-pattern *candidates* |
| 24-hour limit is tight for integration | Several services and correctness invariants | Stop after each phase, prioritize testing, keep UX explicitly out of scope |

### A note on design changes

This blueprint deliberately resolves necessary gaps in the source plan (partial-fill collateral accounting, seller collateral policy, Redis sorting, stable event identity, gross realized-PnL definition, runtime DB identity and event retry behavior). These are **proposed design decisions** to make the current architecture implementable. Codex must record them and apply them consistently, not present them as features already delivered by the repository. If implementing any decision requires a new SQL table or an incompatible API/schema change, it must STOP and ask the human to approve the exact minimal change.

---

## 11. Final backend definition of done

The backend is complete for this sprint **only when**:

- Existing 13-table ER model is preserved; incremental SQL setup and all declared DB routines/triggers/views work on the configured local database.
- Authenticated trading endpoint accepts two crossing orders, risk-reserves money, matches via the current pure in-memory book, settles atomically, releases correct reserves and updates gross position PnL.
- Fenwick range-volume and prefix-sum rolling VWAP return verified correct values.
- Redis has correctly price-sorted top-20 live depth, including update and delete semantics.
- Neo4j stores weighted counterparty edges, deduplicates execution retries, detects a seeded ring and supports retention cleanup.
- pgvector calculates/stores 6-D market feature vectors and returns nearest-neighbor matches; PostgreSQL FTS returns indexed disclosure matches with admin-only RLS.
- SQL exercises all required constructs, backed by query outputs and optimizer plans.
- Simulator + unit/concurrency/integration/benchmark suites run; pass/fail/blocked status is factual, with no unsubstantiated timings.
- API endpoints and backend documentation are sufficient for a future Next.js frontend to consume **without changing contracts**.
- `frontend/**` is untouched, **Codex performs no Git commits or pushes**, and the user receives an exact phase-by-phase handoff.

**Not part of backend completion:** completed Next.js pages, recorded UI demonstration, production-grade event durability, horizontal scale, exchange-grade custody, or experimentally proven microsecond matching. These should never be marked complete from backend work alone.

---

## 12. Minimal first instruction to send Codex now

```text
Read docs/architecture/TradeGraph_Codex_Backend_Master_Plan_Minimal_Reviews.md
fully and follow the execution gate protocol above. Execute Batch A only:
Phase 0 must be completely read-only; then automatically execute Phase 1
if no exception blocker exists. Preserve the exact source-plan order,
existing 13-table schema, existing directories, and all baseline tests.
Do not touch frontend/, stage, commit, push, or mutate GitHub.
STOP after Phase 1 with a complete test/contract/ER/diff report.
```

After reviewing and approving this result, use **Prompt 2** under the batch-invocation section to authorize Phases 2–11. Do not manually invoke each technical phase.

---

## Appendix A — Original-plan requirement traceability (no backend feature omitted)

This matrix is a **checklist**, not a statement that a feature already works. Each original day and underlying DBMS syllabus item must be linked to observed tests/output before Codex marks it complete.

| Original item (23-page plan) | Original intended artifact | Implement/verify in local phases | Completion evidence required |
|---|---|---|---|
| Day 1 schema / ER / constraints / seed / GRANT / REVOKE / ALTER / DROP | `db/schema.sql`, `db/seed.sql`, `docs/er/tradegraph-er.md` | 0–1 | schema verifier, actual ER/DDL and 13 tables |
| Day 1 Postgres+pgvector, Redis, Neo4j Compose | `docker-compose.yml` | 1 | parsed config, actual service health |
| Day 2 race-proof reserve procedure | `db/procedures/place_and_reserve_order.sql` | 2 | two/eight-way overspend, rollback |
| Day 2 independent matcher, FIFO, price/ticks and cancellation | `backend/matching/order_book.py`, matcher unit tests | 2 | randomized differential oracle + edge cases |
| Day 3 API reservation→match→TradeEvent | `backend/api/`, `backend/events/`, `backend/risk/` | 3 | committed order and emitted fill |
| Day 3 login bcrypt/JWT + app.role/native role | `backend/auth/`, `backend/api/routes/auth.py` | 3 | trader/admin login and API/DB RBAC denial |
| Day 3 BIT and prefix VWAP ring | `backend/matching/fenwick.py`, `rolling_vwap.py` | 2–3 | O(log M)/O(1) correctness and benchmarks |
| Day 3 GROUP BY HAVING | `db/queries/price_band_having.sql` | 3–5 | correct grouped volume result |
| Day 4 atomic settlement/ordered lock | `db/procedures/settle_execution.sql` | 4 | two-account concurrent settlement test |
| Day 4 execution→position/PnL trigger | `db/triggers/update_positions.sql` | 4 | after-insert financial state tests |
| Day 4 order-book view | `db/views/order_book_view.sql` | 5 | actual view result |
| Day 4 recursive desk CTE | `db/queries/recursive_desk_rollup.sql` | 5 | hierarchy volume/PnL result |
| Day 4 SQL VWAP window, maker/taker sets | `db/queries/rolling_vwap.sql`, `set_operations.sql` | 5 | window values + set query evidence |
| Day 4 archival `DELETE RETURNING` into `order_history` | `db/queries/order_archive.sql` | 5 | archive rows retained, active rows deleted |
| Day 5 Redis top-20 sorted set and eviction | `backend/stores/redis_depth.py` | 6 | sorted best prices, `ZADD`/`ZREM`/`DEL` |
| Day 5 Neo4j weighted trader graph and ring | `backend/stores/neo4j_graph.py`, `db/neo4j/*.cypher` | 7 | 3-trader loop, MERGE update, DELETE |
| Day 6 regime 6-vector/HNSW/upsert/delete | `backend/stores/regimes.py`, vector SQL | 8 | nearest neighbors and retention query |
| Day 6 FTS `tsvector`/GIN + admin RLS | `db/queries/full_text_search.sql`, admin API | 8 | real ranked search + denied trader |
| Day 6 1NF→4NF and BCNF/Armstrong | `docs/architecture/normalization-proof.md` | 8,11 | worked valid proofs, no new tables |
| Day 6 EXPLAIN seq/B-tree/BRIN/covering | `docs/architecture/query-optimization.md` | 5,10 | actual plans and measured timings |
| Day 7–8 Next.js login/trade/optimizer/surveillance | `frontend/` | **Excluded this sprint, not removed** | future frontend gate |
| Day 8 end-to-end simulation, role demo, latency isolation | simulator + integration + benchmarks | 9–10 | real store outputs, slow-worker comparison |
| Day 8 report and README | existing README, docs/architecture | 11 | complete backend evidence; UI screenshots later |

### Backend syllabus concepts that must be **explicitly demonstrated**, not left implicit

- **Unit 1:** ER relationships, weak identifying entities, primary/foreign keys, 13-table reduction, constraints and selection/projection/join/aggregate examples.
- **Unit 2:** `INSERT`, `UPDATE`, `DELETE`, `SELECT`; `JOIN`, `GROUP BY/HAVING`, `ORDER BY`; *nested and correlated* subqueries; `INTERSECT` or `EXCEPT`; recursive desk CTE; SQL views; stored reservation/settlement; PnL trigger; SQL rolling VWAP using a window function; full-text search.
- **Unit 3:** recorded `EXPLAIN ANALYZE` for seq/B-tree/BRIN/covering indexes and comparison to Fenwick; explicit FD set; Armstrong inference/attribute closure; worked 1NF→BCNF→4NF including hypothetical violation/decomposition.
- **Unit 4:** transactions, row locks, deterministic account lock ordering; native role grants/RLS; Redis ordered depth create/update/delete; Neo4j MERGE/update/cycle/delete; `VECTOR(6)` normalized features with HNSW similarity/upsert/delete.
- **Separate rubric:** Next.js is mandatory for the **final** course evaluation, but the current user has explicitly deferred it. Codex must therefore mark final full-project compliance **INCOMPLETE** until frontend and final demonstration exist.

## Appendix B — Exact repository placement policy

**Existing root:** `.env.example`, `.gitignore`, `README.md`, `requirements.txt`, `pytest.ini`; **one planned root file** `docker-compose.yml` may be created as specified in original Day 1. Never create a second project root, new migration framework, new monorepo folder, or new database.

**Existing implementation directories and designated files:**

```text
backend/
  config.py
  api/main.py, api/dependencies.py
  api/routes/auth.py, orders.py, market.py, admin.py
  auth/security.py, auth/rbac.py
  risk/order_reservation.py
  matching/order_book.py, engine.py, price_level.py, reference_matcher.py,
           fenwick.py, rolling_vwap.py
  events/trade_event.py, dispatcher.py
  clearing/settlement.py
  stores/postgres.py, redis_depth.py, neo4j_graph.py, regimes.py
  workers/settlement_worker.py, cache_worker.py, graph_worker.py, regime_worker.py
  simulator/market_simulator.py

db/
  schema.sql, seed.sql
  procedures/place_and_reserve_order.sql, settle_execution.sql
  triggers/update_positions.sql
  views/order_book_view.sql
  queries/order_archive.sql, price_band_having.sql, recursive_desk_rollup.sql,
          rolling_vwap.sql, set_operations.sql, full_text_search.sql,
          vector_similarity.sql
  neo4j/constraints.cypher, seed.cypher, wash_trade_cycles.cypher,
        retention.cypher

scripts/
  setup_day1.sh, verify_schema.py, seed_demo_accounts.py, run_simulation.py

tests/
  conftest.py
  unit/test_matching_engine.py, test_matching.py, test_order_book.py,
       test_fenwick.py, test_rolling_vwap.py
  concurrency/test_reservation.py, test_double_spend.py,
              test_settlement_locks.py
  integration/test_database_integrity.py, test_rbac.py,
              test_order_pipeline.py, test_polyglot.py
  benchmarks/test_matching_latency.py, test_latency_isolation.py

docs/
  er/tradegraph-er.md
  architecture/day1-decisions.md

frontend/      # NEVER MODIFY IN THIS BACKEND SPRINT
```

**Preauthorized new files within existing directories** (because original deliverables need homes): `docs/architecture/backend-contracts.md`, `normalization-proof.md`, `polyglot-data-models.md`, `query-optimization.md`, `backend-demo.md`; `scripts/setup_backend.sh`; and optionally `db/procedures/cancel_order.sql` after user accepts the exact financial contract. All other new files require a path-and-purpose proposal before writing. A missing *directory* is never permission to invent one. Existing empty stubs should be used before creating files.

## Appendix C — Codex prompts and human-controlled commit handoff

The canonical two prompts are in **§0, Human-to-Codex batch invocation**. Do not use the older one-phase-at-a-time instructions. At every internal phase boundary, Codex must append to `docs/architecture/backend-implementation-progress.md`:

```text
PHASE N: <name> | STATUS: PASS / BLOCKED / FAIL
SOURCE DAY: <original Day 1–6 or Day 8>
EXACT FILES CHANGED: <paths; no frontend files>
FEATURES / CONTRACTS IMPLEMENTED: <precise behaviors>
TESTS EXECUTED: <command, pass/fail counts; no fabricated results>
SERVICE EVIDENCE: <SQL/API/Redis/Cypher/vector outputs where applicable>
13-TABLE ER UNCHANGED: YES / EXCEPTION STOP
REGRESSION CHECK: <results>
NEXT ACTION: AUTO-ADVANCE / PLANNED REVIEW / EXCEPTION STOP
```

At each planned checkpoint, give the full diff, `git diff --check`, `git status --short`, tests, remaining limitations and original-plan rubric traceability. User alone reviews, stages, commits and pushes. No front-end work occurs in either batch.

---

### References

- Repository: <https://github.com/SudarshanG9/TradeGraph>
- Existing schema: <https://github.com/SudarshanG9/TradeGraph/blob/main/db/schema.sql>
- Existing ER: <https://github.com/SudarshanG9/TradeGraph/blob/main/docs/er/tradegraph-er.md>
- Existing risk guard: <https://github.com/SudarshanG9/TradeGraph/blob/main/db/procedures/place_and_reserve_order.sql>
- Existing matcher: <https://github.com/SudarshanG9/TradeGraph/blob/main/backend/matching/order_book.py>
- Existing design decisions: <https://github.com/SudarshanG9/TradeGraph/blob/main/docs/architecture/day1-decisions.md>
- Original uploaded architecture plan: `tradegraph-architecture-plan.md.pdf` (23 pages).
- Original uploaded course rubric: `DBMS Level 3 Project Requirements.pdf` (5 pages).
