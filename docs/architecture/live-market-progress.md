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
