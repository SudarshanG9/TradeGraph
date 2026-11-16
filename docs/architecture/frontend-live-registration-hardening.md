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

Phase 0 commit: `27333d8`, pushed successfully. Backend unit baseline: 203 passed.
Isolated combined baseline: 257 passed, 1 failed, 33 fixture errors; investigating
fixture schema/environment gaps before interpreting these as product regressions.

## Phase 1 — canonical origin and CSRF

Status: FIXED for tested validator behavior; browser mismatch redirect deferred to
same-origin proxy phase. Original policy conflated every denial as CSRF_REJECTED.
Updated `app-origin.ts`, `session-core.ts`, `.env.example`, and session tests:
strict canonical URL syntax; distinct missing-header, missing-origin, foreign-origin,
cross-site and alternate-loopback error codes. Neither host headers nor a login
exception expands origin trust. HTTPS production and explicit loopback test policy
are preserved. Session cookies still derive security from the configured origin.
Tests: frontend suite/typecheck run in this phase; see following commit evidence.
No API/DB relationship changes. No production configuration changed.
