# Frontend–backend integration ledger

## Scope and baseline — 16 November 2026

Work is confined to the existing clone at `/Users/sudarshan/Documents/GitHub/TradeGraph`.
Fetched `origin` before inspection: local and remote main both pointed to
`78fa541f629e146386d6b38c2a8fd9d0a07ae273`. Integration branch:
`integration/frontend-backend`. Preserve the approved frontend composition and all
existing backend financial, identity, schema and matching contracts.

The initial working-tree difference was Next.js's generated `next-env.d.ts`:
the running development server selected `.next/dev/types`. A production build
regenerated production declarations and formatting restored the tracked baseline;
no user-authored changes were discarded. The development server was stopped for
dependency installation and baseline verification. No external API owner was running.

### Existing architecture

The client PreviewProvider owns a mock session, catalog, selected instrument and
createMockServices adapter. Pages use typed Services calls and useResource, which
currently performs one read per mount/invalidation. Authentication guards are
client-only. All actions and data remain mock-only at this audit checkpoint.

FastAPI owns JWT verification, current database identity/role enforcement,
reservation, matching admission and cancellation. PostgreSQL settlement is the
financial authority; Redis depth and Neo4j are derived. The live supervisor uses
the same coordinator and owner lease as human orders. No duplicate matching owner,
WebSocket, registration, reset, direct browser database access or CORS change is needed.

### Page dependency map

All authenticated pages depend on the catalog (`instruments.list`, GET /instruments),
server session and role protection. All reads need empty/error handling; timed-out
mutations require reconciliation rather than automatic retry.

| Page | Components / service | FastAPI endpoints | Role | Refresh / complexity |
|---|---|---|---|---|
| Authentication | AuthPage, SignInForm; auth.login | POST /login | Public | Explicit submit; high: session/CSRF/expiry |
| Dashboard | AccountSummary, PositionsTable, RecentOrders, ExecutionsTable | /account/me, /orders/me, /market/{symbol}/trades | Trader | Initial/action/5s; medium |
| Terminal | OrderBook, PriceChart, OrderForm, MarketMetrics | /market/{symbol}/book, trades, analytics; POST /orders | Trader | Book/trades ~1.5s; high: partial availability, uncertain outcomes |
| My Orders | OrderHistory, CancelDialog | /orders/me; POST /orders/{id}/cancel | Trader | Cursor pages/action/~2s; high: reconciliation |
| Analytics | VwapPanel, PriceBandPanel, ExecutionsTable | /market/{symbol}/analytics, trades | Trader | Active reads; band query explicit; medium |
| Account | AccountSummary, PositionsTable | /account/me | Trader | Initial/action/~5s; low |
| Admin Overview | HealthCards, SimulatorControls | /health; /admin/simulator/status,start,stop | Admin | Status ~2.5s; high: real lifecycle and uncertain stop |
| Surveillance | CycleCandidates, CycleGraph | /admin/surveillance/cycles | Admin | Explicit refresh; medium: graph unavailable |
| Regimes | RegimeSearch, RegimeResults | /admin/regimes/similar | Admin | Explicit only; medium: current capture writes, no observations |
| Disclosures | DisclosureSearch, DisclosureResults | /admin/disclosures/search | Admin | Explicit only; low: metadata/rank only |
| Optimizer | OptimizerControls, PlanPanel | /admin/optimizer/compare | Admin | Explicit only; medium: expensive recursive plans |
| Desks | DeskRollup, DeskExplanation | /admin/desks/rollup | Admin | Initial/manual; low: overlapping rollups |

### Contract gaps and minimal resolution

- Existing response field names match route models. Wire integer tokens must be
  decoded with parseWire, validated, then normalized to Int strings. Bounded
  instrument/count metadata and finite nonfinancial decimals need separate checks.
- Services.auth currently returns mock-only PreviewSession. Add a live session
  representation without returning FastAPI tokens to browser JavaScript.
- No server BFF, sessions or guards exist. Add an explicit allowlist, private
  FASTAPI_BASE_URL, secure server session and origin/CSRF enforcement. FastAPI
  remains the final identity/role authority.
- Dashboard hardcodes Alice and ACME; terminal/analytics contain fixture band
  defaults. Use actual selected catalog metadata and clearly specified query bounds.
- RegimeSearch imports a fabricated current vector. Omit those values in live
  mode: current=true returns similarity matches, not a standalone current vector.
- AcceptedOrder is OPEN acceptance, not a settlement result. Submit/cancel need
  stable request keys, pending/unknown states and subsequent authoritative reads.
- Simulator currently shadows status with local mock state. Live rendering must
  follow returned status; transport failure cannot fabricate backend ERROR/STOPPED.
- No polling currently exists. Add bounded, nonoverlapping, visibility-aware reads,
  backoff and stale-response cancellation; retain last successful snapshots.
- No public registration/reset/refresh/revocation endpoint exists. Preserve honest
  unavailable registration UI. No provisioning or authorization-policy change.

### Planned modification boundary

Frontend lib transport/validation/session/adapters; allowlisted app API handlers;
server role layouts; provider/resource lifecycle; existing auth/trader/admin
components; targeted tests; safe environment example and runbooks. Preserve the
mock adapter and tests under explicit development-only configuration. No backend
change is planned. Any independently verified backend defect needs a documented,
narrow regression-tested exception. Schema, financial formulas, matching engine,
data stores and existing tests must remain intact.

### Baseline evidence

- Locked npm install passed (60 packages, audit: zero vulnerabilities). Initial
  npm ci encountered ENOTEMPTY in a dependency directory; the retry succeeded.
- TypeScript passed; all 16 frontend tests passed. Production build passed with
  all existing pages and aliases. Formatting passed after generated declaration
  regeneration; the source working tree was clean.
- First native backend run: 283 passed / 1 failed, 86.52s. The failure was HTTP
  401 immediately after successful fixture login in
  test_api_actual_regime_generation_and_admin_fts_access. The unchanged isolated
  test passed (3.53s). A full rerun is required before declaring phase 0 verified.
- No integration implementation or live UI acceptance has been completed yet.

Phase completion and commit evidence will be appended only after successful checks.

### Phase 0 verification complete

Full unchanged backend rerun: **284 passed**, one existing Starlette/httpx
warning, 59.04s. The initial authentication failure did not reproduce; its cause
is unconfirmed and is retained above rather than concealed. Frontend checks all
passed. Phase 0 changes are this audit document only; no runtime behavior changed.

## Phase 1 — native runtime verified

Phase 0 remote commit: `f9c05903304c13591f7629985daf1919fcdf313f`.
Initial push encountered a connection reset; ordinary retry succeeded and remote
HEAD matched. No force push was used.

The existing schema verifier passed: 13 tables, 18 foreign keys, vector/pgcrypto,
RLS, grants, indexes and demo associations. Bot dry run validated all eight
existing identities without changes. No installation, migration or provisioning
was needed. After all native tests finished, one Uvicorn worker was started on
127.0.0.1:8000. Readiness checker exited 0: PostgreSQL/Redis/Neo4j and derived
workers up, three active instruments, eight valid bots, zero active orders,
trading_ready=true, overall_health=ok, no warnings or failures. OpenAPI/catalog
and simulator registration checks passed. No account or financial rows were
changed by readiness verification.

Runtime command: `.venv/bin/uvicorn backend.api.main:app --host 127.0.0.1 --port 8000 --workers 1`.
Stop this owner before native tests that instantiate another coordinator. The
frontend BFF will use private FASTAPI_BASE_URL=http://127.0.0.1:8000. Preserve
existing ignored backend environment; never copy credentials into frontend code.

## Phase 2 — transport foundation

Phase 1 remote commit: `c4de28d84ec5664345ff8dd4aa5adf240ca9ec4e`.
Added explicit operation allowlist/query/body validation, lossless response schemas,
private server transport, safe machine-code errors/timeouts/aborts, real data
adapter and safe environment example. Existing pages remain mock-only until the
session boundary is installed in phase 3. Public route wiring is intentionally
coupled to that authorization boundary; no unguarded proxy is exposed.

Checks: strict TypeScript, **26 frontend tests**, formatting and production build
passed. Transport tests cover 401/403/409/422/503, malformed data/content type,
BIGINT roundtrips, route/query/body allowlists, timeout/abort uncertainty and no
transport retry. An actual native FastAPI health request through transport-core
returned ok, all four dependencies up and trading_ready=true. No backend source
or database schema changes. Sessions, UI integration and real trading acceptance
remain outstanding; the data adapter is not yet selected by the UI.

## Phase 3 — authenticated BFF and role boundary

Phase 2 remote commit: `dfbd75ea92c353df56cd891e0e5675c075c8150d`.
Wired allowlisted Next.js routes behind server sessions, independent role checks
and CSRF checks, including existing GET operations with capture/expensive effects.
JWTs remain exclusively in a bounded process-local Next.js session map. Browser
cookies contain random 256-bit IDs with HttpOnly/SameSite=Strict/expiry; Secure
is enabled for HTTPS APP_ORIGIN. Restart logs users out; this deployment requires
one Next.js instance. Logout removes its server session, not backend JWT revocation.
Server layouts restrict direct role pages. Production cannot enable mock shortcuts.
Sign-up remains unavailable and grants no roles.

Verification: 28 Node tests passed, strict types/format/build passed. Real HTTP
acceptance through production Next.js and the existing single FastAPI owner
passed using the repository's scoped synthetic account fixture: both roles,
missing identity, selected-role mismatch, cross-role API/page denial, catalog,
logout and CSRF. Next.js streams unauthorized page redirects with HTTP 200;
assertions verify the actual expired/forbidden redirect destination. The initial
status-only expectation failed and was corrected after inspecting that response.
Session expiry/tamper/role behavior is separately covered by deterministic unit
checks. No existing test assertions or backend files were changed.

Remaining: page-specific mock wording/assumptions, polling, uncertain-action UX,
full browser and financial acceptance. The live adapter is now selected by default.

## Phase 4 — live catalog and account reads

Phase 3 remote commit: `fce18cd6e5cfc7b66bccd45709b9fb8cba2f4d70`.
Dashboard/account use authoritative account responses and active catalog metadata.
Removed fixed Alice/ACME identity assumptions; missing catalog never invents an
instrument. Position details resolve against current data instead of a saved row.
Added visibility-aware, nonoverlapping resource scheduling with bounded backoff,
cleanup and account abort signals; account/dashboard refresh every five seconds.
Explicit action invalidation retains mounted feedback rather than resetting it.

Strict TypeScript and all 28 Node tests passed. Real BFF acceptance expanded to
catalog/account: **2 native HTTP tests passed**, exact synthetic fixture cash
20000/escrow 0, empty positions, actual catalog ID and string tick/lot units.
No account provisioning beyond existing scoped test fixtures or schema change.

## Phase 5 — real order operations

Phase 4 remote commit: `ea740f644f11000cb41d73bdc0bfe08defb6cfe6`.
Order/cancel UI now describes actual backend acceptance and cancellation. Submission
uses one key per intent, a synchronous duplicate guard and a tab-persistent unresolved
intent marker written before dispatch. Timeout/disconnect cannot silently generate a
new submission after navigation/reload; operator reconciliation is required. No
balance or execution is synthesized. Cancellation failures refresh server facts.

Checks: 29 Node tests, strict types, production build passed. **3 native HTTP tests
passed** including resting SELL 100 x 3, unchanged empty execution history, duplicate
key/funds/invalid-price rejection, crossing BUY 105 x 1 settled at maker 100,
seller PARTIAL 1/3, buyer FILLED, cursor history, cancellation of remaining 2,
released escrow, converged Redis depth and VWAP 100/band volume 1. Only isolated
fixture accounts/instrument were used. The first cancellation test omitted the
JSON content type and returned 415; its request was fixed, readiness confirmed
zero persisted active orders, and the single test API owner was cleanly restarted
before rerunning. No backend behavior or assertions were weakened.

Uncertain submission reconciliation cannot be fully automatic because the backend
has no durable request-key lookup. The tab stays locked pending operator review;
this conservative limitation will be documented in the final handoff.

## Phase 6 — independent market polling and execution chart

Phase 5 remote commit: `6de751b5540b2058967322fd6f401b878c3573af`.
Terminal now polls book, committed executions and analytics independently at
1.5-second completion-based intervals. A Redis failure no longer hides successful
trade/chart/account observations. Last snapshots remain visible with explicit
error/delay notices; quiet stale depth does not claim financial failure. Requests
abort on cleanup/instrument changes, pause hidden tabs and back off to 30 seconds.
No monotonic-version assumption prevents recovery after a backend restart.

Execution IDs are deduplicated losslessly and instrument-scoped; the chart retains
up to 1,000 observed records, fetching the latest 100 each refresh. The view labels
this bounded coverage and never interpolates missing trades. Analytics use real
settled VWAP and explicit full supported price bounds. Orders poll every 2 seconds.

Verification: 30 Node tests, strict types, formatting and production build passed.
The phase 5 real BFF acceptance already proved resting depth without trades,
settled maker-price execution, actual partial status, book convergence and real
analytics; this phase adds independent UI refresh and exact history tests. Full
browser polling/visual proof remains part of phase 15 acceptance, not claimed here.

## Phase 7 — Trader consistency cleanup

Phase 6 remote commit: `cbf9c6afa1e9d98c53cfc7948dd363517e45c74c`.
Removed remaining unconditional mock labels from shared Trader observations and
empty states. Price-band queries now start with explicit full supported bounds,
validate the Redis-safe limit, abort superseded queries and retain submitted
bounds alongside results. Account/order invalidation and polling share the same
adapter; no optimistic settlement or separate balance cache exists.

Strict types and five targeted component tests passed; all three native BFF
acceptance tests passed again against the updated production build (4.19s).
