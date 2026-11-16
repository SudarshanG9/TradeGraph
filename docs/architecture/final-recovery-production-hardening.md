# Final recovery and production hardening

Base: `9c4c64ded6f7129460eca8ff0e810dc60be09e84`.
Branch: `codex/final-recovery-production-hardening`.
Only durable recovery and production transport/stability are in scope.

## Phase 1: failure windows

Audit covers dispatcher, settlement worker, reservation coordinator, pure matcher/book,
TradeEvent, all derived workers/stores, startup, reservation/settlement/cancel SQL,
and restart diagnostics. PostgreSQL is the financial authority.

| Crash boundary | Committed SQL | RAM lost | Replay / risk / startup |
|---|---|---|---|
| Reservation begins, before COMMIT | None; transaction rolls back | Request | Retry via request key; no financial effect |
| Reservation COMMIT, before matcher | Order, escrow, optional request identity | Admission progress | Ambiguous: indistinguishable from resting order; startup refuses active orders |
| Matcher changes book, before events | Reservations only | FIFO removals, fills, STP decision | Unsafe to reconstruct pending matching from SQL; no committed execution identity |
| Events generated, before queue | Reservations only | Exact IDs, time, ordered fills | Unsafe; execution sequence gaps do not describe a fill |
| Settlement queue / transaction before COMMIT | Reservations; earlier fills may be committed | Remaining events | Rollback applies no financial effect; partial batch cannot be reconstructed exactly |
| Financial COMMIT before analytics | Execution, positions, balances, fill counts | Analytics / event progress | Exact TradeEvent reconstructable: canonical ID and greatest(order IDs) taker; settlement replay exact-match idempotent |
| Analytics before consumer handoff | Same canonical SQL | Queued derived work | Analytics replay safe by canonical ID; graph absolute aggregate rebuild safe; historical book observations absent |
| Redis / Neo4j / pgvector | Same; possibly regime snapshot | In-flight delivery and observation | Redis rebuild only from verified book; graph absolute aggregate replay safe; missing historical regime input cannot be invented |
| WebSocket send | Same | Connection queues | Best effort; reconnect requires authoritative HTTP snapshot; never financial replay |

`execution` contains every TradeEvent field except taker, which settlement enforces
as `greatest(buy_order_id,sell_order_id)`. It does not contain contemporaneous depth
or capture-time regime inputs. Regime snapshots already committed remain available;
missing historical observations are inherently non-reconstructable with current data.

A second owner is excluded by the session advisory lock. After owner death an
active-order check refuses startup; no orders are canceled. Historical execution
replay is bounded and idempotent. Startup must not be relaxed based on timestamps:
they describe reservation, not completed matching, and SQL fill counts lag RAM.

Phase 1 tests: `tests/concurrency/test_recovery_windows.py`, plus existing settlement
recovery tests. Test environment is newly created `tradegraph_test_final_hardening`
on dedicated PostgreSQL/Redis ports, never the configured financial database.
Phase status and exact verification/commit evidence follow below.

Phase 1 verification: **16 passed** (new crash-window suite and existing settlement
recovery suite, real isolated PostgreSQL, 6.53 seconds). Branch creation and initial
push confirmed by origin. No running financial process was killed. No financial
routine or matching rule was modified. Commit recorded in the next phase entry.
