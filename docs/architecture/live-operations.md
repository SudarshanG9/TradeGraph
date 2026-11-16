# Live notification protocol and proxy

Local canonical origin: http://127.0.0.1:3000. Next listens on 127.0.0.1:3001,
FastAPI on 127.0.0.1:8000. Start `node deploy/local-proxy.mjs` with APP_ORIGIN,
NEXT_INTERNAL_ORIGIN and FASTAPI_BASE_URL set to those fixed destinations.
The loopback-only proxy streams HTTP to Next and upgrades only /live/ws to FastAPI.
/api/backend/* always stays behind Next validation. Wrong loopback GET navigation
with HTML Accept redirects to the configured canonical URL; POST is rejected 421,
never replayed. Foreign Host is rejected. Socket cookies/Authorization are stripped.

Set matching APP_ORIGIN and ALLOW_INSECURE_LOOPBACK_ORIGIN=true on backend and
frontend for local production-mode tests. Never use this exception for nonloopback
HTTP. Real production uses a TLS edge such as deploy/Caddyfile.example, explicit
HTTPS APP_ORIGIN, WSS, secure cookies, internal backend bind/firewall and one owner.
The final hardening report records real isolated Caddy validation; validate the
exact hostname/configuration again for each deployment.

POST /api/live/ticket is cookie-authenticated and CSRF-protected. It exchanges the
server-held JWT for a Redis-backed single-use 20-second random ticket. Connect with
subprotocols `tradegraph.v1` and `ticket.<ticket>`; server negotiates only the former.
Never log subprotocol request headers. No credential goes into URLs. Revocation is
bound to the opaque session hash and checked every 10 seconds; JWT expiry also
closes connections. Redis auth outages close live access rather than bypassing it.

Subscribe/unsubscribe messages have only `type` and up to 8 active instrument IDs.
Private order/account notifications are implicitly scoped to authenticated trader,
admin simulator events to admin role. V1 notifications include schema_version,
type, owner epoch, per-connection sequence and published_at; book events add
instrument_id/version; committed trades add canonical execution_id. No balances,
personal fields or private trader IDs are sent. A connection's sequence is contiguous
across authorized deliveries, avoiding false gaps from other users' private events.

Limits: 4 sockets/user, 1024 global, 128 queued messages/socket, 30 inbound messages
per 10 seconds, 1024-character application message bound, 5-second send timeout,
10-second heartbeat/auth recheck, 45-second inactivity expiry. Deployment must also
apply an edge frame/body size limit; uvicorn runner sets ws-max-size. Slow receivers
close 1013 and require snapshots. Graceful shutdown cancels tasks and drops clients.
Notifications are best effort; SQL/HTTP snapshots and bounded polling reconcile loss.

## Recovery and production cutover

The final hardening branch validates Caddy v2.11.9 with real isolated HTTPS/WSS.
See `final-recovery-production-hardening.md` and `production-stability-results.md`
for exact measurements and remaining blockers; public DNS/ACME issuance must still
be checked for the deployment's actual hostname.

Before starting the updated API, stop admissions and drain the existing owner.
Use the configured installation identity to review/apply
`db/migrations/20261117_durable_event_outbox.sql` through:

```bash
.venv/bin/python -m scripts.migrate_recovery --database EXPLICIT_DATABASE --runtime-role EXPLICIT_FINANCIAL_LOGIN --apply
.venv/bin/python -m scripts.reconcile_restart
```

The database argument must match the explicit admin connection; runtime credentials
are never an admin fallback. Backfill adds publication identities, not invented
historic regime observations. Keep missing observations visible. Do not mark them
delivered using today's book. Do not delete executions/outbox rows to clear health.
Retain completed outbox rows until a separately reviewed retention policy exists.

Set `TRADEGRAPH_DOMAIN=your.actual.hostname` for Caddy and the same
`APP_ORIGIN=https://your.actual.hostname` for both Next and FastAPI. Set
`ALLOW_INSECURE_LOOPBACK_ORIGIN=false`. Bind Next on 127.0.0.1:3001 and FastAPI on
127.0.0.1:8000 with one worker, `--ws-max-size 2048` and `--no-access-log`.
Keep PostgreSQL/Redis/Neo4j private and expose only Caddy's HTTP/HTTPS ports.
Use existing private session/JWT keys. Validate the exact deployed Caddyfile before
starting it; its automatic TLS redirects HTTP and the application rejects a foreign
WSS origin. Never enable raw header/debug logging: ticket subprotocols are secrets.

Health reports durable publication installation, pending/retrying outbox rows and
missing historical observations. Derived retry is independent of settlement; a
financial or ownership failure requires operator reconciliation. Health checks are
read-only. OPEN/PARTIAL orders and terminal accounting mismatches refuse startup.
No automatic cancellation or rematching is authorized by this tooling.

To reproduce isolated verification, create a NEW test-stack directory using
`scripts.create_test_stack`, then use `scripts.with_test_environment` with its
private runtime and admin-password files. Set `TRADEGRAPH_CADDY` to a real binary
for the TLS and capacity pytest suites. The soak runner accepts `--caddy`,
`--duration-seconds 1800`, `--output` and `--interruptions`; `--browser-module` points
to an installed Playwright module. All fault injection/metrics helpers refuse
non-test databases. They are not production server entry points.
