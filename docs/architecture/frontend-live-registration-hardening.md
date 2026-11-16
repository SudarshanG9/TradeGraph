# Frontend, registration and live reliability implementation

Starting main: `ccd5374d018af95b4a71ca0540f6ebb3538c2181`.
Branch: `codex/frontend-live-registration-hardening`. Never merge automatically.

## Phase 0 — audit

Status: PARTIALLY_FIXED (audit complete; full native reproduction pending).

Confirmed in source: bootstrap catches every session failure and sets null;
`startPolling.refresh()` drops refresh while pending; dashboard `Promise.all`
couples three independent resources; signup creates no records; no live endpoint
exists. These source findings are not claimed as browser reproductions.

Inspected authentication/session/transport, all requested backend financial paths,
identity installer, schema and request/RLS migrations. Matching ownership and
COMMIT boundaries must remain unchanged. Registration needs an operator-owned
provisioner because HTTP credentials deliberately cannot create roles.

Tests added: `frontend/tests/session-recovery.test.ts` exercises store outage and
recovery without deletion and authoritative missing-cookie behavior.

Baseline: frontend 38 passed, 2 native Redis tests skipped; typecheck and formatting
passed. Production build failed because the environment denies a build worker
binding a port (Turbopack/PostCSS); native retry pending. Backend unit, concurrency,
and isolated native suites pending. No production dependency was restarted.

Existing uncommitted auth placeholder and generated Next types edits were preserved
while switching from the previous branch. Branch creation and initial push succeeded.
Commit SHA and test evidence are appended after each phase push.

## Acceptance policy

FIXED means tested behavior in the stated environment. PARTIALLY_FIXED means some
required behavior remains. BLOCKED identifies an unavailable dependency or unsafe
action. NOT_VERIFIED means no execution evidence. No UI mock or open socket counts
as full financial acceptance. Never run a second owner on the existing database.
