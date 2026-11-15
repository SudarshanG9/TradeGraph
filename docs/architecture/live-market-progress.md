# Live market implementation ledger

## Phase 0 — audited baseline

- Branch: `main`; HEAD: `7e607cab6b8a622676ab6da3e026ee968061d815`.
- Initial working tree clean; no applicable AGENTS.md files found.
- Baseline: `.venv/bin/python -m pytest -q` with native service access:
  **192 passed**, one existing Starlette/httpx deprecation warning, 47.25 seconds.
- Sandbox-only attempt: 116 passed, 5 failed, 71 errors due to denied local
  network access. Native checks and subsequent native tests run outside that sandbox.
- PostgreSQL, Redis, Neo4j reachable. Exactly 13 public tables; zero unresolved
  active orders. Runtime login is NOINHERIT, nonsuperuser, without BYPASSRLS.
- Reuse Coordinator.admit/cancel/book_snapshot, shielded committed_io,
  SettlementWorker.drain, existing derived workers, NewOrder and existing RBAC.
- Existing deterministic simulator and fixture cleanup audited and preserved.
- Planned additions: provisioning CLI, pure strategies/model, supervisor,
  separate admin router, focused tests, architecture/runbook documentation.
  Minimal existing modifications: FastAPI lifecycle/router registration, README.
- Risks: in-process nondurable event queue; unresolved orders refuse startup;
  cleanup must precede finish_admissions. Runtime cannot read KYC: provisioning
  validates KYC administratively; startup validates allowed trader/margin/desk/tier.
- Configuration discrepancy: only eight identities are authorized, despite the
  suggested 4–12 range. Support 4–8 and reject 9–12 rather than invent identities.

## Phase 1 — persistent bot provisioning

- Added `scripts/seed_live_bots.py` and native rollback tests
  `tests/integration/test_live_provisioning.py`; created this ledger.
- Exact immutable allowlist; random bcrypt credentials, bounded funding,
  transaction/advisory lock, strict association validation. Dry run is read only;
  reruns never change existing financial or identity records.
- Tests and commit: recorded after execution below.
- Phase 1 verification: provisioning + existing database-integrity/RBAC tests:
  **32 passed**, one existing warning (13.17s). No original source modified.
- Phase 1 commit: `fb55e1b837f780127b7d75ace119391f9f44f006`.
- Post-commit audit caught that a provisioning test entered conn.transaction()
  before the rollback fixture had begun a transaction. That created the approved
  bot accounts persistently. All conflict mutations were rolled back; no ordinary
  data changed. Added an explicit outer transaction to make every test isolated.
  Explicit dry-run and two CLI apply invocations validate all eight persistent
  accounts; both applies preserve them. Follow-up verification recorded below.
- Isolation follow-up: same native selection **32 passed**, one warning (9.42s).

## Phase 2 — pure reference model and strategies

- Added `backend/simulator/market_model.py`, `backend/simulator/agents.py`, and
  `tests/unit/test_live_agents.py`. No existing runtime files modified.
- Immutable observations/actions/account/order snapshots; local seeded randomness;
  passive maintained maker quotes, variable noise, momentum, mean reversion.
- Cash plus actual fee budgeting, pending-order inventory bounds, four outstanding
  orders, five lots/order and 1,000,000 minor units/order maximum notional.
- `.venv/bin/python -m pytest -q tests/unit`: **128 passed** (0.68s), including
  all 111 original unit tests and 17 new strategy tests. Next: shared supervisor.
- Phase 1 isolation commit: `3a23a23b2d381cc5f9d836c75224d33554ed19b1`.
- Phase 2 commit: `dae7a49d95128017bb473f00771fcc512aba2228`.

## Phase 3 — bounded live supervisor

- Added `backend/simulator/live_supervisor.py` and lifecycle unit tests in
  `tests/unit/test_live_supervisor.py`. Reuses the supplied coordinator exclusively.
- Config validates active instruments, eight allowlisted accounts, and 4–8 bots.
  One task, monotonic pacing, no catch-up bursts, finite duration and order ledger.
- Stop is shielded from a disconnected caller, waits for in-flight admissions,
  drains settlement, cancels only exact owned run orders, reconciles PostgreSQL,
  then reports STOPPED or ERROR. ERROR requires operator reconciliation/restart.
- Status counts exact execution rows involving run order IDs, never sequence gaps.
- Unit regressions: **142 passed**. Existing native order pipeline and concurrency
  regressions: **44 passed**, one existing warning (28.84s).
- Next: administrative API and lifecycle wiring, without changing old contracts.
- Phase 3 commit: `0f835b7dac403afe5f85a88d54740dde93972c50`.

## Phase 4 — administrative API and application lifecycle

- Added `backend/api/routes/simulator.py` with strict typed start/stop/status
  schemas and existing Compliance Admin dependency. No JWT or public trader
  contract changes. The request cannot select any trader identity.
- Minimal `backend/api/main.py` changes: construct the supervisor with the existing
  coordinator, register the router, stop it before closing admissions/workers.
- Added native `tests/integration/test_live_simulator_api.py`: RBAC, validation,
  concurrent starts, same-owner identity, repeated session, lifespan shutdown,
  and unavailable settlement worker. Bot quotes on existing instruments retain
  their genuine cancelled history; disposable human fixtures never cross them.
- Native API and existing pipeline checks: **14 passed**, one warning (15.62s).
  Unit regressions: **142 passed** (1.85s).
- Next: deterministic human/bot proof through the genuine shared financial path.
