# TradeGraph frontend preview

A Next.js App Router / React / strict TypeScript / Tailwind demonstration built against the supplied 11-screen PDF. All service data and actions are local mocks. No FastAPI connection, database access, registration service or real trading operation is implemented.

```sh
cd frontend
npm ci
npm run dev
```

Open http://127.0.0.1:3000. Use **View as Trader** or **View as Compliance Admin** on Authentication. Optional mock sign-in accepts `alice@tradegraph.sim` or `admin@tradegraph.sim` with the public fixture password `preview-only`. These values never authenticate with the backend. Only a mock role flag and expiry are stored in sessionStorage; credentials are never stored. Local order changes reset on full reload.

The sidebar's **Preview scenarios** exposes populated, empty, loading, stale, unavailable, large-integer and no-active-instrument fixtures. Action outcomes cover accepted, partial, filled, rejected and unknown previews. In the administrator preview, the unknown outcome demonstrates a failed simulator stop with ERROR and disabled restart. Reload the frontend to begin a fresh mock demonstration.

```sh
npm run typecheck
npm test
npm run format:check
npm run build
npm start
```

See [implementation record](IMPLEMENTATION.md), [verification evidence](VERIFICATION.md), and [future integration handoff](INTEGRATION.md). The original mockup's currency signs, health latency and desk names are unsupported by the API and have been replaced with contract-aligned values. Minor text/button contrast adjustments support accessibility. A separate Account screen reuses Dashboard components because no separate reference was supplied.
