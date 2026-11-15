# Frontend verification

Executed locally on 16 November 2026 (Asia/Kolkata), using the supplied PDF mockups and the actual repository route models. Screenshots are under evidence/. These are visual comparisons, not an automated pixel-difference claim.

## Automated checks

- Strict TypeScript with no emit.
- Node test runner via tsx: exact wire parsing/serialization, BIGINT balances/seeds/notional, lot/price limits, role/session errors, cursor/cancellation semantics, selected-instrument executions, inclusive bands, simulator config/ERROR handling, missing instruments, plan parameter consistency, custom-vector validation and mock action outcomes.
- React server-render checks: exact financial card output, cancelled residual semantics, empty/extreme-value line chart, directed edge counts and nested plan nodes/aggregate rows.
- Production Next.js build; all intended routes and existing aliases resolve.
- Prettier check and git diff --check.

Final results are recorded in IMPLEMENTATION.md after the final run.

## Browser checks through the in-app browser

| Workflow                 | Observed result                                                                                                                   |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| Auth modes/roles         | Sign In / Sign Up and Trader / Administrator selection work                                                                       |
| Registration             | Matching passwords show registration unavailable; no credentials saved or account-created claim; mismatch validation works        |
| Mock identity authority  | Admin fixture credentials with Trader selected are rejected for role mismatch                                                     |
| Trader navigation        | Dashboard → Terminal → My Orders → Analytics → Account; active navigation and shared shell retained                               |
| BUY preview              | Exact estimate and accepted demo feedback persist after refresh                                                                   |
| SELL preview             | BETA quantity 11 rejected for lot size 10; quantity 20 with partial outcome appears as filled 10 / unfilled 10 in My Orders       |
| Cancellation             | Native confirmation dialog, CANCELLED status and explicit non-resting residual explanation verified                               |
| Cursor history           | Next loads only IDs below next_before_id; previous restores the earlier cursor                                                    |
| Analytics                | Inclusive 95–105 mock band yields 140 ACME units; selected instrument scopes execution rows                                       |
| Administrator navigation | Overview → Surveillance → Regimes → Disclosures → Optimizer → Desks                                                               |
| Simulator                | RUNNING → STOPPING → STOPPED; unknown stop yields ERROR with disabled restart; no bot process started                             |
| Surveillance             | Selecting five-trader cycle updates exactly its supplied directed edges/counts                                                    |
| Regimes                  | Explicit search shows all six features and sorted distances; empty current query shows missing observations                       |
| Disclosures              | Default query returns metadata/ranks only; no body viewer                                                                         |
| Optimizer                | Nested paired plans render; Recent Executions disables unused instrument/price controls                                           |
| Role separation          | Admin direct Trader route and Trader direct Admin route both denied                                                               |
| Session lifecycle        | Natural 15-minute expiry returns to auth with expiry notice; explicit logout returns to /auth                                     |
| Shared data states       | Empty, error, loading and populated recovery verified on desk analytics                                                           |
| Missing market data      | Empty chart, stale-depth notice and empty active catalog verified; no submit controls without catalog                             |
| Large integers           | 9,007,199,254,740,993 is displayed exactly in account view                                                                        |
| Mobile                   | All eleven authenticated pages tested at 375×812 with document scrollWidth = clientWidth = 375; table overflow stays inside cards |
| Mobile navigation        | Drawer open/close and logout verified; footer stacking issue found and corrected                                                  |

Keyboard-support checks include explicit form labels, visible focus styles, focusable table scroll regions, native dialog focus/escape behavior, and chart point focus tooltips. Contrast math checked: body text 14.59:1 and muted text 6.72:1 on card surface. Secondary text was brightened to remain at least 4.5:1 on both card/input surfaces; blue action text/background contrast was adjusted accordingly. This is a focused accessibility review, not a formal WCAG certification.

## Visual reference mapping

01-auth ↔ PDF 1; 02-dashboard ↔ PDF 2; 03-terminal ↔ PDF 3; 04-orders ↔ PDF 4; 05-analytics ↔ PDF 5; 07-overview ↔ PDF 6; 08-surveillance ↔ PDF 7; 09-regimes ↔ PDF 8; 10-disclosures ↔ PDF 9; 11-optimizer ↔ PDF 10; 12-desks ↔ PDF 11. 06-account reuses PDF 2 components because no distinct account screen was supplied. Additional mobile and large-integer screenshots capture regression scenarios.

The implementation record documents visible contract-driven deviations. No backend, database schema, financial SQL or backend test implementation changed; no changes were pushed.
