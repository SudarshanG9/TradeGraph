# Approved read boundary and pending recovery contract

The trader-read boundary was subsequently approved explicitly and implemented in
6db0bd1; deployment is described in database-identity-deployment.md. The durable
matching journal/outbox below remains unapproved and unimplemented. The earlier
request-identity-table approval alone did not authorize these separate contracts.

## Trusted trader database reads (I-01/I-02)

The current shared login can read multiple traders' financial rows and explicitly
assume compliance_admin_role. A caller-set app.trader_id cannot make that a tenant
boundary. Proposed minimum trusted boundary:

1. Separate auth lookup, financial/matching, compliance and trader-read credentials.
2. Give each trader a dedicated NOINHERIT/NOBYPASSRLS login named from its existing
   UUID (for example tg_<uuid>). No new relational mapping table is required.
3. Use RLS on margin_account, order, order_history and position tied to session_user's
   validated UUID. A trader login must have no membership in another trader role,
   financial service role, owner or compliance role. Missing identity denies reads.
4. After JWT verification, the API chooses that authenticated trader's database
   credential from a server-only secret provider. The browser never receives it.
   Changing app.* GUCs or SET ROLE must not allow a different trader identity.
5. Matching/settlement/cancellation/maintenance and internal simulator use a separate
   service boundary with only documented financial EXECUTE/read grants. Admin
   analytics uses a separately authorized compliance connection. Auth lookup has
   only the fields it needs. API routes never accept a supplied trader ID.

Approval was received for separate runtime credentials, the secret-provider
contract, role lifecycle and RLS policy migration; implementation is verified in
the separate SCRAM cluster. A shared all-trader read credential is not
an acceptable substitute. Files: setup_backend.sh, incremental role/RLS migration,
config.py, postgres.py connection/context methods, API dependencies/orders/admin,
simulator read paths, authorization/concurrency tests and deployment configuration.
Financial locks/formulas stay in existing routines. Rollback disables the new read
routes, drains connections, restores reviewed prior grants/policies, and leaves
financial data intact; rollback explicitly loses the stronger DB read isolation.
Do not apply while the running API still uses the old shared query paths.

## Crash-durable publication and matching restart (I-06/N-05/N-06/A-04)

An execution outbox alone does not reconstruct accepted-but-unmatched orders.
Two separate proofs are required:

- A supplementary execution delivery table, conceptually keyed by execution_id
  with immutable event payload, immutable book snapshot/capture inputs, original
  capture timestamp, graph/regime delivery acknowledgements and creation time.
  Execution plus required delivery input must commit in one transaction. Runtime
  cannot update canonical event contents; delivery acknowledgements are bounded
  and idempotent. No TTL or deletion while a consumer is outstanding.
- Durable admission/matching progress sufficient to reconstruct FIFO, remaining
  quantities, allocated execution identities and matched-but-uncommitted events.
  This could extend the approved request table with admission state plus a
  supplementary immutable matching journal, but exact fields and replay algorithm
  require a reviewed design before implementation. Active orders must remain
  fail-closed until that replay is proven. Never infer an empty event backlog from
  active SQL order status alone.

A minimum outbox migration would use execution_id BIGINT PRIMARY KEY REFERENCES
execution(id), event_payload JSONB NOT NULL, capture_inputs JSONB NOT NULL,
graph_delivered BOOLEAN NOT NULL DEFAULT false, regime_delivered BOOLEAN NOT NULL
DEFAULT false, created_at TIMESTAMPTZ NOT NULL, plus indexes for pending delivery.
This is illustrative, **not permission to create the table**. Capture inputs must
include the exact execution-history visibility boundary, not only a book snapshot:
current Regimes.capture also reads execution history and wall-clock time. If exact
reconstruction is impossible, persist the final deterministic feature vector and
capture timestamp at the proven atomic boundary instead. Legacy missing snapshots
must be labelled unreconstructible, never fabricated.

Files: dedicated migration, reservation/matching admission journal, postgres.py,
settle_execution wrapper/transaction, TradeEvent/capture payload, settlement worker,
graph/cache/regime workers, startup/restart reconciliation, tests and deployment docs.
Preserve canonical execution replay, financial fee/PnL accounting, single owner and
all existing DBMS demonstrations. Graph absolute totals remain retry-safe; regime
capture needs deterministic original inputs. No new broker is proposed.
Rollback disables admissions, drains financial and derived work, retains all request,
journal and outbox identities read-only, then switches consumers only after pending
work is reconciled. Dropping undelivered rows is not a safe rollback.

Approval requested: detailed implementation design for the durable journal/outbox
contract before any additional persisted field/table is created. Native failures
must prove every COMMIT boundary, process-kill point, exact replay/conflict and
old/new-version deployment transition. Current source does not claim crash-durable
lossless delivery or automatic active-order restart.
