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
The Caddy example requires deployment validation; Caddy is not installed here.

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
