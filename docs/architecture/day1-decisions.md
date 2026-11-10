# TradeGraph — Day 1 Architecture Decisions

## Architectural boundary

- PostgreSQL (+pgvector) is the authoritative store for cash, escrow, orders, executions, positions, admin disclosures and microstructure snapshots.
- Redis will cache derived L2 market depth; losing the cache must not lose authoritative state.
- Neo4j will hold derived `EXECUTED_AGAINST` edges for cycle searches.
- The future Python matching engine will keep SQL, Redis, and Neo4j calls outside the matching path.

## Schema and IDs

- Exactly 13 physical PostgreSQL tables (see `db/schema.sql`).
- UUID keys for `user_account`/`trader`; integers for instruments, fee tiers and desks; BIGINT for orders and executions.
- `POSITION` has a composite key `(trader_id,instrument_id)`.
- `KYC_PROFILE` and `MARGIN_ACCOUNT` are identifying dependent entities.
- `DESK.parent_desk_id` models a hierarchy, and `DESK.manager_trader_id` references `TRADER` via an explicit `ALTER TABLE`.
- `ORDER_HISTORY` stores the original order ID with no new sequence. The future archive operation will insert terminal orders into the archive and delete their active rows in the same transaction.
- `EXECUTION.buy_order_id` and `.sell_order_id` preserve order identifiers across archival. Future settlement must verify order ownership and instrument before creating executions.

## Fixed-point convention

- Cash, escrow and realized PnL are BIGINT values in **synthetic minor currency units**.
- `price_ticks` is an integer tick count; `instrument.tick_size` is the number of minor units per tick.
- Gross notional = `price_ticks * tick_size * quantity`; use integer-safe computation and overflow checks. Fee rates are NUMERIC basis points. Fee rounding and exact buyer/seller collateral policy must be frozen before Day 2.
- `lot_size` is currently metadata. If it is enforced as a quantity multiple, add that check to the Day 2 order-reservation function where the instrument is available; a simple row CHECK on `"order"` cannot look up another table.
- **Open design decision for Day 2:** whether SELL orders require settled inventory, a quantity reservation, or permit collateralized shorts. Choose and test one policy before allowing trade matching; a cash escrow column alone does not reserve an existing position.

## Security

- `user_account` has `TRADER` and `COMPLIANCE_ADMIN` application roles, using bcrypt-hashed demo passwords.
- PostgreSQL separately has `trader_role` and `compliance_admin_role`, both NOLOGIN.
- Two RLS policies restrict `market_disclosure` and `regime_snapshot` to the compliance role AND the trusted request context.
- `app.role` is **not an identity check** and can be set by a database client. Real enforcement later must use authenticated requests, least-privileged DB identities/role membership, and controlled DB grants.
- The native PostgreSQL administrator runs Day 1 setup and verification. Runtime authentication will use a separate database identity because superusers bypass RLS.
- Trader role deliberately has no direct UPDATE privilege on `margin_account` or unrestricted INSERT/UPDATE on orders. Day 2's secure SQL routines will be the intended write boundary.

## Normalization and syllabus evidence

- Source plan references `TRADER_DESK_ASSIGNMENTS` as a **hypothetical BCNF violation**. It is not an extra production table. The normalized production model assigns managers to `DESK`.
- The plan's shorthand `order_id → tier_id → maker_fee_bps` is not a functional dependency entirely within the actual `"order"` table (it has no `tier_id` field). Present this as a dependency across a deliberately denormalized hypothetical joined relation, **not** as a property of the production table.
- For 4NF, demonstrate independent multivalued dependencies on a deliberately **denormalized combined relation**, then show decomposition into `MARGIN_ACCOUNT` and `POSITION`. Do not claim the two normalized tables individually violate 4NF without a real dependency analysis.
- Exact 1NF→4NF proof and optimizer evidence are scheduled for Day 6.

## Day 1 verification scope

The checks cover schema objects, constraint enforcement, role switching, RLS, synthetic seed integrity, and service connectivity.

Later phases cover reservation and settlement concurrency, matching correctness and latency, event durability, cycle detection, HNSW performance, API RBAC, and the Next.js UI.

## Known limitations / follow-up

- A CHECK on `desk.parent_desk_id <> id` blocks immediate self-reference but not longer cycles. Guard hierarchical queries from cycles and/or add a trigger later.
- Future execution/event replay needs an idempotency plan to prevent duplicate settlement. The source's 13-table schema doesn't yet define an external immutable event UUID; resolve it before Day 4.
- No matching or transaction path is implemented on Day 1. Do not benchmark it yet.
