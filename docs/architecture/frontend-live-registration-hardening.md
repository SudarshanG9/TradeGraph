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

Phase 1: 41 frontend tests passed, 2 native tests skipped; typecheck passed.
Commit `b049c88`, pushed. Baseline isolated fixture errors were missing dedicated
Redis (connection refused on 6391); a separate Redis server is now running there.

## Phase 2 — session initialization

Status: FIXED in controller regression tests; browser failure injection pending.
Files: `auth-state.ts`, provider, auth client, session recovery tests. Bootstrap now
has loading/authenticated/unauthenticated/temporarily_unavailable states, a retry,
and generation-based protection from stale checks following login/logout.
503/network/timeout/malformed session responses preserve unknown status and hide
protected content; only confirmed absence/401 redirects. BroadcastChannel and
visibility verification reconcile tabs without storing credentials in the browser.
Existing encrypted shared Redis session storage and non-deletion on outages remain.
Tests cover outage/recovery, absent/invalid cookies and stale completion after
login/logout. No DB or public API contract change. Native restart evidence pending.

Phase 2: 43 frontend tests passed, 2 native tests skipped; typecheck passed.
Commit `726d5f9`, pushed.

## Phase 3 — server rendering recovery

Status: PARTIALLY_FIXED until native browser retry verification.
Redis 503 from role-checking layouts previously escaped before child Retry existed.
Both protected layouts now render `ServiceUnavailable` only for typed session 503;
Next redirect exceptions remain untouched. Root `app/error.tsx` catches nested
layout failures (same-segment boundaries do not). Retry refreshes server rendering.
Files: protected layouts, server session helper, shared recovery view, root boundary.
No protected children render on unknown authorization. Raw error messages are not
shown. Verified against this installed Next version's error/proxy documentation,
which uses `retry` in error boundaries. Frontend suite and typecheck pass.
DB/API: unchanged. Server-render outage/recovery browser evidence pending.

Phase 3 commit `25b9fad`, pushed. 43 frontend tests passed, typecheck passed.

## Phase 4 — atomic registration

Status: FIXED for native persistence tests; provisioning is Phase 5.
Added registration state/policy tables and normalized-email uniqueness, a restricted
SECURITY DEFINER transaction, validated registration store/model, POST /register,
normalized login and readiness checks for both login and existing tokens.
Migration installer binds a dedicated auth role; rollback preserves pending states.
Default zero-funded pending verification; explicit synthetic policy supports fixed
starter funds without fake KYC. No existing core relationship or financial routine
changed. Documents: registration-operations.md. Tests: 20 concurrent distinct
accounts, normalized concurrent duplicates, required-insert rollback, bcrypt,
fee/funding/FKs, no fabricated verification, privilege/byte validation.
Native result recorded below after completion. HTTP rate limits follow in Phase 6.
