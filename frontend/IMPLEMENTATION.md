# Frontend implementation record

Baseline: e99bc37, confirmed equal to fetched origin/main. All original frontend files were empty. No reusable components or dependencies existed.

## Design inventory and checklist

Reference: TradeGraph Frontend Mockups.pdf (11 pages), visually inspected at 1600px. Main canvas #090d12, top bar/cards #101722, border #253040, text #e2e8f0, muted #939fb2, blue #3b82f6, green #22c55e. 60px top bar, 220px sidebar, 32px content inset, 18px gaps, 12px card radius. System sans text and monospace financial values. Mobile behavior is not specified: use a collapsible navigation and stacked cards with horizontal scrolling contained inside tables.

| Phase | Page / PDF                      | Components                                                                 | Backend contracts                                    | Gate    |
| ----- | ------------------------------- | -------------------------------------------------------------------------- | ---------------------------------------------------- | ------- |
| 0     | Foundation                      | contracts, fixtures, service interfaces, shell, UI primitives              | all implemented route models                         | passed  |
| 1     | Authentication / 1              | container, mode selector, role selector, sign-in, sign-up, preview         | Login, LoginResponse                                 | passed  |
| 2     | Dashboard / 2                   | header, balances, positions, orders, executions, actions                   | Account, OwnOrders, Trades                           | pending |
| 3     | Terminal / 3                    | instrument, depth, line chart, analytics, executions, order form, feedback | InstrumentCatalog, Book, Trades, Analytics, NewOrder | pending |
| 4     | My Orders / 4                   | status filters, history, details, cancel dialog, cursor controls           | OwnOrders, CancelledOrder                            | pending |
| 5     | Market Analytics / 5            | instrument, VWAP, price band, execution history, cursor controls           | Analytics, Trades                                    | pending |
| 6     | Account / no separate reference | reuse balances and positions from PDF 2                                    | Account                                              | pending |
| 7     | Admin Overview / 6              | health cards, investigation links, embedded simulator                      | HealthResponse, SimulationStart/Status               | pending |
| 8     | Surveillance / 7                | limit, candidate table, directed cycle                                     | Cycles                                               | pending |
| 9     | Regimes / 8                     | mode, six features, on-demand results                                      | Similar                                              | pending |
| 10    | Disclosures / 9                 | query, metadata results                                                    | Search                                               | pending |
| 11    | Optimizer / 10                  | allowlisted scenarios, parameters, paired plan trees                       | Optimizer                                            | pending |
| 12    | Desks / 11                      | aggregate table, recursive explanation                                     | Rollup                                               | pending |
| 13    | Navigation                      | role guards, logout, aliases, end-to-end checks, handoff                   | future BFF only                                      | pending |

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

## Phases 0–1 verification

Strict TypeScript, six financial/service tests and production build passed. Authentication visually compared to PDF 1 at desktop and narrow viewport; sign-up submission confirms no account creation. Screenshot: evidence/01-auth.jpg. Requested role/mode controls increase card height. Components and per-component history are committed. No live integration.

## Phase 2 — Dashboard

AccountSummary, PositionsTable, RecentOrders and ExecutionsTable completed in separate commits; assembled in src/app/trader/dashboard/page.tsx. Refresh and the terminal action work. Exact Account/OwnOrders/Trades fixtures used. Desktop and narrow layouts visually compared with PDF 2; evidence/02-dashboard.jpg. Typecheck and six tests pass. Minor-unit labels replace unsupported dollars; execution rows are scoped to ACME. No backend integration.

## Phase 3 — Trading Terminal

OrderBook, PriceChart, MarketMetrics and OrderForm committed individually and assembled at src/app/trader/terminal/page.tsx. Instrument switching, exact notional/lot checks, BUY/SELL, mock submission and persistent feedback verified. Line chart uses only fixed chronological execution observations with grid, UTC axes, hover/focus tooltip and last-price marker. Typecheck passes; shared contract tests passed. Screenshot evidence/03-terminal.jpg compared with PDF 3; chart has the requested detailed line treatment, units/window corrected to contracts. No simulator controls and no backend integration.

## Phase 4 — My Orders

OrderHistory/OrderDetails and CancelDialog completed with local status filtering, selection, exact original/filled/unfilled quantities, terminal rules, archived indicators and cursor stack. Browser verified confirmation and CANCELLED result, including the explanation that its residual is no longer resting/reserved; Next advances to a smaller-ID cursor. Typecheck passes; cancellation/cursor behavior covered by passing service tests. evidence/04-orders.jpg compares to PDF 4. Filters apply to loaded cursor pages and are labeled accordingly in empty feedback. No backend integration.

## Phase 5 — Market Analytics

VwapPanel and PriceBandPanel committed; reused InstrumentSelector, ExecutionsTable and cursor controls. Exact inclusive price-band calculation verified in browser (95–105: 140 fixture units) and service tests; result bounds remain tied to submitted inputs. Typecheck passes. evidence/05-analytics.jpg compared with PDF 5. Uses the actual 100-fill window and only selected-instrument executions; on-demand mock calculation only. No backend integration.

## Phase 6 — Account & Positions

Reused AccountSummary and PositionsTable; added AccountExplanation in its own commit. Exact balances match Dashboard; position selection shows returned instrument, signed quantity and gross PnL basis. Typecheck and browser interaction/visual check passed; evidence/06-account.jpg. No distinct mockup exists, so the page reuses PDF 2's cards and table without a new design claim. No backend integration.

## Phase 7 — Compliance Overview

HealthCards, InvestigationTools and SimulatorControls committed individually. Exact simulator config bounds, multiple instrument selection, seed precision, active-bot/state display and all returned counters/workers implemented. Browser verified RUNNING → STOPPING → STOPPED with controls disabled appropriately; service test covers ERROR and restart conflict. Typecheck passes. evidence/07-overview.jpg compared with PDF 6, preserving health/tool positions and adding the authorized compact simulator below. No invented latency and no backend calls/bot processes.

## Phase 8 — Surveillance

CycleCandidates and CycleGraph committed independently, with bounded result selection and refresh. Browser verified selection of the five-trader candidate updates only the returned directed edges and counts; UUID disclosure exposes full canonical identities. Typecheck passes. evidence/08-surveillance.jpg compared with PDF 7; candidate labels are explicitly local numbering because API supplies no IDs. Empty/error/loading fixtures available through shared preview scenarios. No backend integration.

## Phase 9 — Market Regimes

RegimeSearch and RegimeResults committed; exactly six finite/nonzero custom features, exclusive query modes and bounded k. Browser verified explicit current-feature search returns sorted snapshots and all six values. Typecheck passes. evidence/09-regimes.jpg compared with PDF 8. No query runs on entry; an initial prompt replaces prepopulated results to avoid implying automatic current capture. Current feature values are explicitly demo fixtures rather than invented response fields. No backend integration.

## Phase 10 — Disclosure Search

DisclosureSearch and DisclosureResults committed independently. Bounded on-demand query, loading/validation/no-result/service errors, rank bars, IDs, nullable instrument and publication dates implemented. Browser verified the default query and metadata rows. Typecheck passes; evidence/10-disclosures.jpg compared with PDF 9. Full text body viewing is deliberately absent; local title matching is labeled as demo behavior. No backend integration.

## Phase 11 — Query Optimizer

OptimizerControls and recursive PlanPanel/PlanTree committed. Explicit compare, two allowlisted scenarios, disabled unused parameters, collapsible nested nodes, times, aggregate rows, dataset and buffer metrics implemented. Browser verified paired plans and Recent Executions disabling instrument/price inputs. Typecheck passes. evidence/11-optimizer.jpg compared with PDF 10. Faster/slower/equal badges compare returned timing values; there is no arbitrary SQL execution or automatic querying. No backend integration.

## Phase 12 — Desk Analytics

DeskRollup and DeskExplanation committed independently. Exact signed PnL and execution volume, local sorting, refresh and shared data states completed. Browser visual check and typecheck pass; evidence/12-desks.jpg compared with PDF 11. Removed unsupported desk names/hierarchy while preserving the table and explanation-card arrangement. No extra totals over overlapping ancestor/child rows. No backend integration.
