# Frontend implementation record

Baseline: e99bc37, confirmed equal to fetched origin/main. All original frontend files were empty. No reusable components or dependencies existed.

## Design inventory and checklist

Reference: TradeGraph Frontend Mockups.pdf (11 pages), visually inspected at 1600px. Main canvas #090d12, top bar/cards #101722, border #253040, text #e2e8f0, muted #939fb2, blue #3b82f6, green #22c55e. 60px top bar, 220px sidebar, 32px content inset, 18px gaps, 12px card radius. System sans text and monospace financial values. Mobile behavior is not specified: use a collapsible navigation and stacked cards with horizontal scrolling contained inside tables.

| Phase | Page / PDF | Components | Backend contracts | Gate |
|---|---|---|---|---|
| 0 | Foundation | contracts, fixtures, service interfaces, shell, UI primitives | all implemented route models | pending |
| 1 | Authentication / 1 | container, mode selector, role selector, sign-in, sign-up, preview | Login, LoginResponse | pending |
| 2 | Dashboard / 2 | header, balances, positions, orders, executions, actions | Account, OwnOrders, Trades | pending |
| 3 | Terminal / 3 | instrument, depth, line chart, analytics, executions, order form, feedback | InstrumentCatalog, Book, Trades, Analytics, NewOrder | pending |
| 4 | My Orders / 4 | status filters, history, details, cancel dialog, cursor controls | OwnOrders, CancelledOrder | pending |
| 5 | Market Analytics / 5 | instrument, VWAP, price band, execution history, cursor controls | Analytics, Trades | pending |
| 6 | Account / no separate reference | reuse balances and positions from PDF 2 | Account | pending |
| 7 | Admin Overview / 6 | health cards, investigation links, embedded simulator | HealthResponse, SimulationStart/Status | pending |
| 8 | Surveillance / 7 | limit, candidate table, directed cycle | Cycles | pending |
| 9 | Regimes / 8 | mode, six features, on-demand results | Similar | pending |
| 10 | Disclosures / 9 | query, metadata results | Search | pending |
| 11 | Optimizer / 10 | allowlisted scenarios, parameters, paired plan trees | Optimizer | pending |
| 12 | Desks / 11 | aggregate table, recursive explanation | Rollup | pending |
| 13 | Navigation | role guards, logout, aliases, end-to-end checks, handoff | future BFF only | pending |

## Resolved design/contract differences

- No currency code or decimal scale is supplied. Use exact minor units instead of the mockup's dollar signs and decimal currency assumption. Tick size is an integer minor-unit multiplier, not 0.01.
- VWAP uses up to 100 settled fills, not the mockup's last 50. Window fill count and as_of are supplied by the mock service.
- Health has no latency measurements; use dependency state and trading_ready only. Preview connectivity is explicitly synthetic.
- Desk response has no name, parent or depth. Preserve table/card layout without inventing organizational names or nesting.
- Cycles have no candidate IDs/names; use local list numbering and canonical UUIDs with full values available.
- Execution history is scoped to the chosen instrument; the mockup's mixed-instrument analytics rows cannot be reproduced as that endpoint response.
- No distinct account screen is supplied. Reuse PDF 2's financial cards and positions layout; do not claim an independently approved composition.
- No separate full frontend specification was supplied beyond the pasted brief. Original architecture/project requirements are contextual only; actual route schemas control semantics.

All interactions are mock-only, all commits are local, and all implementation changes stay within frontend/. Per-component commits are recorded in Git.
