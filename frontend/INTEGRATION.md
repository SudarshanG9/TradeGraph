# Future FastAPI integration handoff

## Current boundary

`src/lib/contracts.ts` mirrors implemented Python route fields. `Int` means a **normalized exact decimal integer string**, not the wire type. `src/lib/services.ts` exports frontend-facing service contracts and a single deterministic mock adapter. `PreviewProvider` owns the replaceable adapter, role preview, catalog, selected instrument and fixture settings. Components receive normalized records or call this adapter. No application fetch, API proxy, server session, database client, polling loop or market WebSocket is active.

The preview session and its client route guard provide demonstration UX only. The future BFF must independently enforce authorization. A selected frontend role must never override `LoginResponse.role`; `homeFor` maps the actual returned role. `AuthService` documents the future server-side login request/response boundary separately from mock sign-in. Never send a raw access token to client JavaScript or reuse a mock session as real authentication.

## Endpoint replacement map

| Service             | Existing FastAPI route         | Role / notes                                                                |
| ------------------- | ------------------------------ | --------------------------------------------------------------------------- |
| AuthService         | POST /login                    | Server-only; email/password only; actual returned role is authoritative     |
| instruments.list    | GET /instruments               | Both roles; never invent a fallback for an empty catalog                    |
| account.get         | GET /account/me                | TRADER; cash/escrow in minor units, signed positions, gross PnL             |
| orders.list         | GET /orders/me                 | TRADER; limit/before_id and next_before_id; no offset/page-count assumption |
| orders.submit       | POST /orders                   | TRADER; optional Idempotency-Key; 201 acceptance is not settlement          |
| orders.cancel       | POST /orders/{id}/cancel       | TRADER; no body; reconcile unknown outcomes before retries                  |
| market.book         | GET /market/{symbol}/book      | Both; derived top-20 depth, stale/as_of/version                             |
| market.trades       | GET /market/{symbol}/trades    | Both; committed execution history, cursor paging                            |
| market.analytics    | GET /market/{symbol}/analytics | Both; inclusive price band, decimal-string VWAP, up to 100 fills            |
| health.get          | GET /health                    | Dependency states/trading_ready only; no latency contract                   |
| surveillance.cycles | GET /admin/surveillance/cycles | Admin, limit 1–100, candidate cycles only                                   |
| regimes.similar     | GET /admin/regimes/similar     | Admin; exactly current=true OR six features, k 1–100; explicit action only  |
| disclosures.search  | GET /admin/disclosures/search  | Admin; q 1–500, metadata only                                               |
| optimizer.compare   | GET /admin/optimizer/compare   | Admin; allowlisted price_band/recent_executions; explicit expensive read    |
| desks.rollup        | GET /admin/desks/rollup        | Admin; desk_id/PnL/volume, no parent/name fields                            |
| simulator.start     | POST /admin/simulator/start    | Admin; validated config, no trader UUID in body                             |
| simulator.stop      | POST /admin/simulator/stop     | Admin; no body; success only at STOPPED, even on HTTP 200                   |
| simulator.status    | GET /admin/simulator/status    | Admin; active_bots, exact counters, derived-worker readiness                |

## Exact numbers

1. Read FastAPI response text on the server. Use `parseWire` **before** ordinary JSON parsing: every integer token becomes bigint, fractional numbers remain lossless number objects, decimal-string VWAP remains a string.
2. Validate the actual response shape, field enums and bounds. Normalize financial values, quantities, IDs/cursors and counters using `normalizeInteger`. Normalize bounded metadata (instrument IDs, bot/window counts) with `boundedNumber`; explicitly validate finite six-feature/rank/distance/timing decimals. Do not cast the unknown parse result directly to a contract.
3. Pass normalized strings through the BFF's JSON to client components. `fmt` and financial calculations use BigInt. Prices, notional, remaining quantities, cash totals and signed PnL never pass through floating point. No currency or decimal scale is inferred.
4. Serialize outgoing orders with `serializeOrder` and simulation seeds with `serializeSimulationStart`; integer tokens must be JSON numbers for strict Pydantic bodies, not quoted strings. Transport them server-side without an intermediate Number conversion. Keep request fields allowlisted.
5. `validateOrder` checks positive ticks, the Redis-safe price bound, BIGINT quantity/notional and lot multiple. It does not replace backend risk/collateral/fee checks. Both sides reserve cash; estimated notional excludes fees.

The line chart converts only bounded pixel ratios to Number; exact price labels remain strings/BigInt. It draws chronologically sorted execution observations with straight segments, no candles, invented extrema, random prices or volume bars. The mock 100-observation cap is only a preview data limit. Future historical aggregation/decimation or additional cursor fetching must be explicitly specified before presenting broader intervals.

## Session and error work still required

Implement the approved same-origin Next.js BFF with a private backend URL, secure server-side token handling, HttpOnly/Secure/SameSite cookies, CSRF protection, expiry handling and authoritative server role checks. Forward sanitized backend error envelopes. Do not add permissive CORS, browser database access or unapproved backend routes.

On 401, clear the real session and require login; on 403, refuse access. A request timeout never proves no reservation or execution committed: reconcile own orders, account and committed executions before any retry. Mock submission and cancellation states illustrate these semantics without touching financial state. Future action error types should replace local Error messages at the adapter boundary.

The backend has no registration/password-reset/refresh-token/backend-logout endpoint or admin approval workflow. Sign-up must remain unavailable until an explicitly approved provisioning implementation exists. Administrator sign-up requires invitation/provisioning; frontend selection grants no privilege.

## Refresh configuration (inactive)

`futureRefresh` records intended active-view cadences: depth and executions 1.5 s; orders 2 s; account 5 s plus after trading actions; simulator status 2.5 s. These are configuration values only. When activated, pause outside active views, prevent overlapping/stale requests, and reconcile after actions. Surveillance, regime capture and optimizer stay on demand; current=true can capture/upsert a regime and must not be prefetched or polled. No market WebSocket architecture is planned.

## Deliberate preview limits

- Local fixtures are illustrative records, not a financially reconciled live exchange ledger; mock fills never alter cash or claim settlement.
- Regime current features are a labeled demo fixture. The similarity endpoint does not expose a standalone current-feature vector: the future UI must obtain an approved source or omit unavailable values instead of inventing fields.
- FTS preview uses simple local title matching; the real service must preserve PostgreSQL search/ranking semantics.
- Plan timings/row counts/buffers are illustrative mock plan objects. No actual SQL is executed.
- Desk hierarchy cannot be drawn from aggregate IDs alone. No names, parents, universal speedup, current portfolio value, unrealized PnL or unsupported market metrics were invented.
- State examples are selected through an unobtrusive review panel; this panel must be removed or environment-gated in a later real deployment.
