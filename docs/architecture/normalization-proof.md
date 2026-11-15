# Normalization proof for the preserved TradeGraph schema

This proof separates the logical business relations from deliberately generated
or derived physical data. It creates no table. Every capitalized counterexample
below is hypothetical, not a fourteenth production relation.

## Keys, dependencies and relational reduction

The 13 production relations and declared candidate keys are:

| Relation | Candidate keys | Principal dependencies |
|---|---|---|
| user_account | id; email | each key → hash, role, created_at |
| desk | id; name | each key → parent_desk_id, manager_trader_id |
| trader | id; user_account_id | each key → desk_id, full_name, created_at |
| kyc_profile | trader_id | trader_id → pan_hash, verified, verified_at |
| fee_tier | id; tier_name | each key → maker_fee_bps, taker_fee_bps |
| margin_account | trader_id | trader_id → cash, escrow, fee_tier_id, updated_at |
| instrument | id; symbol | each key → tick_size, lot_size, is_active |
| order | id | id → trader, instrument, side, price, quantity, filled, status, times |
| order_history | original id | id → retained order attributes, archived_at |
| execution | id | id → instrument, two order IDs, two traders, price, quantity, executed_at |
| position | (trader_id,instrument_id) | composite key → net_quantity, realized_pnl, updated_at |
| market_disclosure (base projection) | id | id → instrument_id, title, body, published_at |
| regime_snapshot | id; (instrument_id,captured_at) | either key → features |

Neither manager_trader_id nor full_name is unique. A manager may manage many
desks. Execution buy/sell-order pairs and timestamps are not unique: partial
fills can repeat them. Role constraints and CHECKs are predicates, not invented
functional dependencies. Nullable desk/parent/manager/instrument references
retain their actual optional cardinalities; UNIQUE candidate keys listed above
are NOT NULL in DDL.

USER_ACCOUNT has at most one TRADER, with the unique account FK. KYC_PROFILE
and MARGIN_ACCOUNT are identifying dependents whose PK is the trader FK.
POSITION resolves trader/instrument association using its composite key.
EXECUTION resolves the recursive counterparty association; desk self-parent
models hierarchy. There are 18 physical FK edges. Execution order identifiers
are intentionally not FKs so original IDs survive archive deletion.

## Armstrong inference and attribute closure

Consider only the hypothetical joined relation
`OrderFeeJoined(O,T,F,M,K)`: order ID, trader ID, fee tier, maker bps, taker bps.
For the approved fixed-basis demo use FDs O→T, T→F, F→MK.
This does NOT assert fee_tier_id is physically on the order table.

- Reflexivity: TF→F because F is a subset of TF.
- Augmentation: O→T implies OI→TI when adding instrument I.
- Transitivity: O→T and T→F imply O→F; with F→M imply O→M.
- Decomposition: F→MK implies F→M and F→K.
- Union: the latter two imply F→MK.

Closure O+ starts {O}, adds T, then F, then M/K: O+={O,T,F,M,K}; O is a key.
T+={T,F,M,K} and F+={F,M,K}, so neither T nor F is a key of the joined relation.
The empty closure contains no attributes, making the singleton key O minimal.
Production separation of order ownership, margin tier and fee schedule removes
these cross-relation transitive redundancies without adding a new entity.

## Worked 1NF → 2NF → 3NF → BCNF

1. An unnormalized order-fee report with arrays of fills is not 1NF. Expand fills
   into scalar execution rows, keeping a stable execution ID; do not store arrays
   of cash movements in a business column. VECTOR(6) is a typed analytics feature,
   not an unnormalized collection of business records.
2. In a hypothetical line relation `(order_id,instrument_id,trader_name,price)`,
   assuming order_id alone identifies an order, `(order_id,instrument_id)` is NOT
   a candidate key (it is nonminimal). Do not use that false key to claim 2NF.
   A valid partial-dependency example is a hypothetical
   `PositionReport(trader_id,instrument_id,trader_name,instrument_lot_size,net_qty)`:
   key is the pair, trader_id→trader_name and instrument_id→instrument_lot_size
   are partial dependencies. Project trader and instrument descriptors into
   their existing relations; position retains attributes depending on both.
3. OrderFeeJoined has a singleton key and is 2NF, but O→T→F→M/K is transitive
   nonkey dependence. Decompose into OrderOwner(O,T), TraderTier(T,F), Fee(F,M,K).
   Each common determinant is a key in its projected relation, giving lossless
   joins (intersection determines a projection) and dependency preservation.
   The existing order, margin_account and fee_tier realize these responsibilities.
4. Hypothetical `TRADER_DESK_ASSIGNMENTS(T,D,G)` has T→D and D→G (manager).
   T is a key; D is not. D→G violates BCNF, and also 3NF because G is nonprime.
   Do not falsely call this particular example 3NF-but-not-BCNF. Project (T,D)
   and (D,G). Their intersection D determines (D,G), so the join is lossless;
   both FDs remain enforceable. Existing trader.desk_id and desk.manager_trader_id
   are exactly this normalized placement. No assignment table is created.

Under the declared FD set, all nontrivial determinants of logical base relations
in the key table above are superkeys. Independent position facts depend on both
trader and instrument; manager depends on desk, and fee rates depend on fee tier.
Thus these base projections meet BCNF under the stated domain assumptions.

## Genuine 4NF counterexample, kept hypothetical

For a hypothetical extension with multiple collateral accounts per trader,
consider scalar `FinancialKeys(T,A,I)`: trader, collateral account, position
instrument. Suppose account membership and instrument positions are independent.
T→→A and T→→I are nontrivial MVDs; key is TAI, and there are no nontrivial FDs.
It is BCNF but violates 4NF because T is not a superkey for either MVD.

For T=Alice with accounts {cash,margin} and instruments {ACME,BETA}, independence
requires all four tuples:

```text
Alice cash   ACME
Alice cash   BETA
Alice margin ACME
Alice margin BETA
```

Decompose to hypothetical Accounts(T,A) and Positions(T,I). Their natural join
recovers exactly the Cartesian product for each trader, so the MVD decomposition
is lossless. Account and instrument descriptors then attach to their own keys.
These are PAPER relations only. The actual schema has one margin account per
trader (A is identified by T), and position has instrument-dependent quantity/PnL.
Its separate margin_account and position responsibilities are already stronger
than this extension: they do not independently violate 4NF. There is no extra
currency, collateral-account ID or authorization attribute in production DDL.

## Honest physical exceptions and limits

The implemented market_disclosure includes generated body_tsv. Since
(title,body) deterministically determines that generated value, treating it as
an ordinary independent stored attribute would introduce a non-superkey FD and
invalidate a blanket BCNF claim for the physical row. The BCNF proof above is
for the base projection excluding this deliberately generated search derivative.
The generated column/GIN is an explicit physical access optimization preserved
from the source, not an inconsistency repaired by an unauthorized schema rewrite.

Position is also a materialized financial summary of execution history, and
Redis/Neo4j are deliberate cross-relation projections. Recomputable derivatives
do not justify pretending every physical object is an independent normalized
base fact. No hidden business FDs/MVDs are assumed; new business rules or mutable
historical fee bases would require a new analysis and explicit approval. The
worked proofs and actual keys support the existing ER, not a claim of completed
UI, optimizer performance or full course compliance.
