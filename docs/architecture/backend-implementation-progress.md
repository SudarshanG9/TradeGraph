# Backend implementation progress — Batch A review

Local repository: `/Users/sudarshan/Documents/GitHub/TradeGraph`; branch `main`;
HEAD `1a5fa87c83b5888eecdbef3bf27b203e91a49eb3`.
Date: 14 November 2026 (Asia/Kolkata).

## Phase 0 — read-only audit, original Day 1 baseline

RESULT: PASS after the user's environment repairs and source-document attachment.
No repository file, .env, schema or seed change was made during Phase 0.
This historical audit entry was created during Phase 1, not during Phase 0.

- Audited tree: 81 tracked files, 19 nonempty, 62 empty placeholders. Baseline
  schema, seeds, ER, Day 1 decisions, matcher, reservation SQL, README, bootstrap,
  verifier, seeder and all nonempty tests were inspected. No applicable AGENTS.md
  was found. Existing package markers remain empty.
- First audit preserved a modified .env.example and untracked master plan. The
  resumed audit also found user-created db/seed_users.sql, which is untouched.
- Original PDFs now accessible at `/Users/sudarshan/Downloads/tradegraph-architecture-plan.md.pdf`
  and `/Users/sudarshan/Downloads/DBMS Level 3 Project Requirements (1).pdf`.
  All substantive architecture pages 1–23 and the five rubric pages were read;
  architecture page 24 is blank. No document instruction overrides the user's
  native-only, backend-only and no-Git-mutation constraints.
- The first audit had unavailable PostgreSQL/Docker and missing source documents.
  On resumption the user supplied native PostgreSQL and PDFs; Neo4j first failed
  with root-owned logs/data. The user repaired and started it. Final service
  verification below passes. No ownership/data/credential reset was performed.
- The default shell Python lacks psycopg; the existing project .venv has the
  necessary dependencies. All successful tests use `.venv/bin/python` 3.13.0.
- Pure matcher baseline: 18 passed (0.50s on first audit; 0.54s on resumed audit),
  including four independent 2,000-order randomized differential runs.
- Safe read-only PostgreSQL verifier now passes all 24 checks. ER and schema have
  the same 13 persistent tables and 18 physical FK relationships. Original checks,
  roles, forced RLS, generated FTS field, GIN and VECTOR(6)/HNSW are retained.
- pg_proc catalog shows no installed place_and_reserve_order function. This is an
  expected Phase 2 prerequisite, not a Phase 1 regression. No installation ran.
- Day 1 fixtures were inspected: their DML rolls back in finally; sequences can
  advance normally. Such tests were run only in Phase 1, not during read-only audit.
- Native service substitution for Docker is explicitly authorized by the user.
  No Docker/Compose action or file is required under that newer instruction.

Gate decision: AUTO-ADVANCED to Phase 1 after native health and document access
were verified. No schema or architectural blocker remained for Phase 1 types,
settings and review documentation.

## Phase 1 — contracts, preserved ER and native infrastructure

RESULT: PASS for Phase 1 implementation and its focused checks; contract version
`1.0-review` awaits the planned human review. This is not completed API/clearing.
Source day: original Day 1 completion. Gate: PLANNED REVIEW #1. Batch B NOT STARTED.

Files modified (existing placeholders reused where available):

- `/Users/sudarshan/Documents/GitHub/TradeGraph/backend/config.py`: lazy, immutable
  native settings, separate runtime DB credentials, bounded health/queue/JWT
  settings, one-worker enforcement, safe validation and secret-redacted repr.
- `/Users/sudarshan/Documents/GitHub/TradeGraph/backend/events/trade_event.py`:
  immutable typed event, existing Fill adapter, strict numeric/UUID/time checks,
  UTC normalization and deterministic JSON/dictionary round trips.
- `/Users/sudarshan/Documents/GitHub/TradeGraph/tests/unit/test_matching.py`:
  86 focused contract/configuration cases and independent exact fee-ledger checks;
  existing matching tests were preserved unchanged.
- `/Users/sudarshan/Documents/GitHub/TradeGraph/.env.example`: retain database and
  legacy setup keys; add native runtime/Redis/Neo4j/health settings. Replace the
  pre-existing literal JWT example with a placeholder. The user's .env is untouched.

Files created in the existing architecture directory (no suitable placeholders):

- `/Users/sudarshan/Documents/GitHub/TradeGraph/docs/architecture/backend-contracts.md`:
  versioned field-level API/event/accounting/ER/store/identity contracts and native
  verification/safe future SQL installation order.
- `/Users/sudarshan/Documents/GitHub/TradeGraph/docs/architecture/backend-implementation-progress.md`:
  this required phase evidence ledger and review report.

DB OBJECTS CHANGED: none. No tables, columns, keys, routines, triggers, policies,
grants, indexes, application roles or service identities were created/altered.
13-TABLE ER PRESERVED: YES. FRONTEND UNTOUCHED: YES.
Existing Order, Fill, MatchResult and OrderBook public interfaces unchanged.
New TradeEvent and Settings interfaces are proposed in version 1.0-review.
requirements.txt, pytest.ini, scripts, all existing nonempty tests and the
original decisions document needed no changes. No new dependency is required.

### Architectural and financial decisions for approval

1. Preserve integer minor units/ticks, exact NUMERIC basis points, cash collateral
   for both sides, collateralized shorts, monotonic lifecycle and maker pricing.
2. Approve the proposed fee-collection timing in backend-contracts.md: BUY fee
   advances from released fee collateral, exact aggregate maker/taker fee refund
   at terminal processing; SELL cumulative actual fees paid from proceeds.
   This qualifies immediate per-fill BUY actual-fee debits in the master plan.
   It has NOT been implemented in SQL. Denial means settlement must wait for an
   agreed alternative; do not silently implement different accounting in Batch B.
3. Preserve exact R(q) escrow release, pooled-account separation, fixed fee/tick
   bases through the demo/replay history. No new fee ledger/snapshot column.
4. One globally serialized reservation→commit→submit admission owner, increasing
   order IDs, cache=1 and no other writer make maker/taker history reconstructible
   from order IDs after archival. This invariant needs future integration tests.
5. Preallocated execution IDs, payload-checked idempotent settlement, deterministic
   account/order locks and post-commit derived consumers remain later work.
6. The proposed bounded in-process queue is not crash durable. Accepting the demo
   limitation does not prove the source's unconditional no-loss requirement.
   Lost events cannot be reconstructed automatically; stop admissions and require
   operator reconciliation. No automatic replay/rematching is claimed.
7. Runtime login provisioning/actual privilege verification remains Phase 3, and
   the current native admin credentials are never used by the new runtime config.
   Import/type/config tests do not prove a live least-privileged API connection.

Worked ledger, starting cash 20000 per trader, limit/execution=100, quantity=100,
tick_size=1, maker BUY fee=1bp, taker SELL fee=2bp:

| State | BUY cash/escrow | SELL cash/escrow |
|---|---:|---:|
| Reserved | 9998 / 10002 | 9998 / 10002 |
| 50 filled | 9998 / 5001 | 19998 / 5001 |
| Then cancel 50 | 14999 / 0 | 24999 / 0 |
| Alternative: fill all 100 | 9999 / 0 | 29998 / 0 |

One 100-unit fill and 100 one-unit fills have identical final results and fees
1/2. Naive CEIL per tiny fill would charge 100 each against reserved fee 2.
SELL limit 100, execution 105, quantity 100 has actual 2bp fee=3, paid from
proceeds despite reserved fee=2; final SELL cash=30497. Tests cover these values,
one-tiny-fill cancellation, empty cancellation, BUY price improvement, mixed
roles/rates, 100 randomized partitions and large-notional fractional rounding.
These are independent contract calculations, not executed PostgreSQL settlement.

### Exact test commands and results

From the repository root; PYTHONDONTWRITEBYTECODE and no cache provider avoid
unnecessary workspace cache writes. Native DB checks ran outside the network
sandbox, with the same existing .venv and configured local connection.

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/unit/test_matching.py tests/unit/test_matching_engine.py -q
........................................................................ [ 69%]
................................                                         [100%]
104 passed in 0.56s

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider -m day1 -q
..................                                                       [100%]
18 passed, 124 deselected in 0.49s

PYTHONDONTWRITEBYTECODE=1 .venv/bin/python scripts/verify_schema.py
24 PASS assertions; DAY 1 READ-ONLY VERIFICATION PASSED

git diff --check
exit 0; no output
```

No failed or skipped cases in these runs. Deselected cases are the other phase
markers/unmarked units, not disabled tests. No tests were weakened, skipped,
deleted or replaced. Phase 2 reservation/concurrency tests were not run because
the function is not installed and Phase 2 is not authorized. No full-backend,
API, settlement, simulator or latency/performance PASS is claimed.

Verifier output:

```text
PASS: Exactly 13 application tables (found: ['desk', 'execution', 'fee_tier', 'instrument', 'kyc_profile', 'margin_account', 'market_disclosure', 'order', 'order_history', 'position', 'regime_snapshot', 'trader', 'user_account'])
PASS: Both NOLOGIN application roles subject to RLS
PASS: vector and pgcrypto extensions
PASS: Two admin RLS policies
PASS: RLS enabled and forced on both admin tables
PASS: Required order, execution, GIN, HNSW indexes
PASS: Composite position primary key
PASS: 18 foreign key relationships (found 18)
PASS: Archive IDs are preserved (no independent ID default)
PASS: Scratch DROP TABLE completed
PASS: user_account: at least 4 rows (4)
PASS: trader: at least 3 rows (3)
PASS: kyc_profile: at least 3 rows (3)
PASS: margin_account: at least 3 rows (3)
PASS: fee_tier: at least 2 rows (2)
PASS: instrument: at least 3 rows (3)
PASS: desk: at least 2 rows (2)
PASS: Recursive desk relationship seeded
PASS: Desk manager seeded
PASS: Four demo accounts with expected roles and bcrypt hashes
PASS: All three demo traders have margin and KYC records
PASS: Trader has no disclosure SELECT grant
PASS: Trader cannot directly update balances
PASS: Compliance administrator has disclosure grant
DAY 1 READ-ONLY VERIFICATION PASSED
```

### Native service and catalog evidence

| Dependency | Actual observation |
|---|---|
| PostgreSQL | 17.12 (Homebrew), configured /tmp socket, verification PASS |
| pgvector / pgcrypto | 0.8.7 / 1.3 |
| Redis | 8.10.2; redis-cli PING exit 0, PONG |
| Neo4j | Kernel 2026.09.0 community; authenticated RETURN 1 AS healthy -> 1, exit 0 |
| Sequence caches | execution_id_seq=1, order_id_seq=1 |
| Canonical trading rows | active orders=0, executions=0 |
| Reservation catalog | function absent; install in Phase 2 |
| Runtime login | tradegraph_runtime absent; provision in Phase 3 |
| Docker/Compose | excluded by user, not a failed/missing acceptance dependency |

Neo4j version query was `CALL dbms.components() YIELD name, versions, edition
RETURN name, versions, edition; RETURN 1 AS healthy;` via cypher-shell, with
NEO4J_PASSWORD passed through its child environment from .env. No secret was
included in the command or report. Redis PING/INFO server and PostgreSQL catalog
queries were read-only. No schema bootstrap, seeding or service start/reset was
repeated in the completed Phase 1 run; services were already running after the
user's repair.

The 18 observed FK edges match the existing ER: desk→desk/trader;
trader→user_account/desk; kyc_profile→trader; margin_account→trader/fee_tier;
order→trader/instrument; order_history→trader/instrument;
execution→instrument/buy trader/sell trader; position→trader/instrument;
market_disclosure→instrument; regime_snapshot→instrument.

### Source/rubric traceability and limitations

| Original requirement | Batch A evidence / remaining work |
|---|---|
| Day 1 schema/ER, role/GRANT/RLS, seeds | existing live verifier and 18 Day 1 tests PASS; structure unchanged |
| Day 1 service topology | all three native services verified; Docker exclusion user-authorized |
| Exact matcher and independent oracle | existing 18 regressions PASS; no matching algorithm changes |
| Financial/event/API/security contracts | version 1.0-review; immutable event/config code and 86 tests; accounting/queue decisions need review |
| Day 2 reservation + BIT/prefix VWAP | pending Phase 2; no installation or algorithm work in Batch A |
| Days 3–6 API/clearing/advanced SQL/stores/proofs | pending Batch B |
| Day 8 simulation/benchmarks/backend report | pending Batch B; no performance claim |
| Next.js and recorded full-project demonstration | explicitly deferred; final course compliance remains incomplete |

NEXT PHASE READY: only after the user approves Batch A and its explicit financial
and crash-boundary decisions, then authorizes Batch B. No scheduled automation,
GitHub mutation, staging, commit, push, branch switch or reset occurred.

### Local diff and status

Final tracked `git diff --stat` and `git status --short` are recorded below after
all report updates. Git's normal diff/stat exclude new untracked documents; those
documents are explicitly included in the separate complete review diff.

```text
$ git diff --stat
 .env.example                  |  33 ++++--
 backend/config.py             | 114 ++++++++++++++++++
 backend/events/trade_event.py |  88 ++++++++++++++
 tests/unit/test_matching.py   | 261 ++++++++++++++++++++++++++++++++++++++++++
 4 files changed, 486 insertions(+), 10 deletions(-)
$ git status --short
 M .env.example
 M backend/config.py
 M backend/events/trade_event.py
 M tests/unit/test_matching.py
?? db/seed_users.sql
?? docs/architecture/TradeGraph_Codex_Backend_Master_Plan_Minimal_Reviews.md
?? docs/architecture/backend-contracts.md
?? docs/architecture/backend-implementation-progress.md
```

The two new architecture documents are untracked and therefore absent from the
tracked stat above. A complete Batch A review diff (tracked changes plus both
new documents) is available at `/private/tmp/tradegraph-batch-a-review.diff`.
It excludes the untouched, pre-existing untracked master plan and seed_users.sql.

COMMIT PERFORMED: NO. PUSH PERFORMED: NO. STAGING PERFORMED: NO.
GATE DECISION: PLANNED REVIEW #1. STOPPED AFTER PHASE 1.


## Phase 2 — PASS (15 November 2026)

Source Day 2. Batch A and fee/queue decisions approved by user. User subsequently
authorized staging, phase commits and GitHub pushes, overriding the earlier ban.
Added pure Engine single-thread ownership and idempotent settled-fill analytics,
sparse-coordinate Fenwick tree (existing-coordinate O(log M), expansion rebuild
O(M log M)), true N+1 cumulative-prefix ring VWAP. Matcher untouched.
Created scripts/setup_backend.sh in existing scripts directory: guarded,
transactional installation of existing reservation SQL; no bootstrap/seeding.
Installer executed twice: installed once, then preserved existing function.
`PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -p no:cacheprovider tests/unit tests/concurrency/test_reservation.py -q`
-> 132 passed in 6.51s. Includes 2/8-client real PostgreSQL races, rollback,
fees/overflow, 4x2000 differential orders, BIT and prefix-ring references.
13-table ER unchanged; frontend untouched; native services baseline PASS.
No API/settlement claimed. NEXT: automatic Phase 3 after phase commit/push.

```text
 backend/matching/engine.py       | 40 +++++++++++++++++++++++
 backend/matching/fenwick.py      | 68 ++++++++++++++++++++++++++++++++++++++++
 backend/matching/rolling_vwap.py | 35 +++++++++++++++++++++
 tests/unit/test_fenwick.py       | 33 +++++++++++++++++++
 tests/unit/test_order_book.py    | 19 +++++++++++
 tests/unit/test_rolling_vwap.py  | 31 ++++++++++++++++++
 6 files changed, 226 insertions(+)
 M backend/matching/engine.py
 M backend/matching/fenwick.py
 M backend/matching/rolling_vwap.py
 M tests/unit/test_fenwick.py
 M tests/unit/test_order_book.py
 M tests/unit/test_rolling_vwap.py
?? scripts/setup_backend.sh
```
