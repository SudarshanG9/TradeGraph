# TradeGraph frontend

Next.js App Router with authenticated FastAPI integration through a strict BFF.
JWTs remain server-side; encrypted Redis sessions survive frontend restarts when the
same key and Redis data persist. Trader signup creates real pending accounts and
requires operator database provisioning before login. WebSocket tickets are limited,
single-use credentials; financial state comes from authenticated HTTP snapshots.

Use the [root local workflow](../README.md#integrated-local-application) to run the
entire application through http://127.0.0.1:3000 (Next internal port 3001). Keep
APP_ORIGIN identical in frontend/backend and use the printed canonical browser URL.
`localhost` is a different origin and state-changing requests are never replayed.

```sh
npm ci
npm test
npm run typecheck
npm run format:check
npm run build
```

Build uses Next's supported webpack backend because Turbopack build workers cannot
bind their internal ports in the restricted test environment. The generated
next-env.d.ts may need Prettier normalization after generation.

Optional UI-only mock mode requires `next dev`, `TRADEGRAPH_MODE=mock`, and separate
local fixture login. Production always uses live mode. Mock signup creates nothing.
See [live operations](../docs/architecture/live-operations.md) and
[registration operations](../docs/architecture/registration-operations.md) for limits,
reconciliation, verification policy and deployment constraints.
