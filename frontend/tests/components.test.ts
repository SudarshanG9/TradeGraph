import test from 'node:test';
import assert from 'node:assert/strict';
import { createElement as h } from 'react';
import { renderToStaticMarkup as render } from 'react-dom/server';
import { PreviewProvider } from '../src/components/preview-provider';
import { AccountSummary } from '../src/components/trader/account-summary';
import { OrderDetails } from '../src/components/trader/order-history';
import { PriceChart } from '../src/components/trader/price-chart';
import { CycleGraph } from '../src/components/admin/cycle-graph';
import { PlanPanel } from '../src/components/admin/plan-panel';
import {
  account,
  largeAccount,
  orders,
  executions,
  cycles,
  optimizer,
} from '../src/lib/mock/fixtures';
test('financial cards render exact totals and gross signed PnL without implied currency', () => {
  const html = render(h(AccountSummary, { account: largeAccount }));
  assert.match(html, /9,007,199,254,740,993/);
  assert.match(html, /9,007,199,255,080,993/);
  assert.match(html, /−9,007,199,254,740,993/);
  assert.doesNotMatch(html, /\$/);
  assert.match(render(h(AccountSummary, { account })), /8,765,000/);
});
test('cancelled quantities remain unfilled but are not presented as resting orders', () => {
  const o = { ...orders[0], status: 'CANCELLED' as const };
  const html = render(
    h(PreviewProvider, { children: h(OrderDetails, { order: o, onCancel: () => {} }) }),
  );
  assert.match(html, /Unfilled Qty/);
  assert.match(html, /no longer resting or reserved/);
  assert.doesNotMatch(html, /Cancel remaining/);
});
test('line chart uses supplied observations only, handles empty and extreme exact prices', () => {
  const html = render(h(PriceChart, { trades: executions.filter((t) => t.instrument_id === 1) }));
  assert.match(html, /<polyline/);
  assert.doesNotMatch(html, /NaN|Infinity|candlestick/);
  const extreme = [{ ...executions[0], price_ticks: '9007199254740993' as const }];
  assert.match(render(h(PriceChart, { trades: extreme })), /9,007,199,254,740,993/);
  assert.match(render(h(PriceChart, { trades: [] })), /No execution history/);
});
test('cycle graph renders exactly one directed edge per returned trader', () => {
  const html = render(h(CycleGraph, { cycle: cycles.candidates[2], index: 2 }));
  assert.equal((html.match(/marker-end=/g) || []).length, 5);
  assert.match(html, /Directed cycle of 5/);
});
test('plan panel preserves nested bitmap index nodes and distinguishes aggregate rows', () => {
  const html = render(
    h(PlanPanel, {
      title: 'Automatic',
      plan: optimizer.plans.automatic,
      dataset: optimizer.dataset_size,
      rowCount: optimizer.row_count,
    }),
  );
  assert.match(html, /Bitmap Index Scan/);
  assert.match(html, /Rows returned \(aggregate\)/);
  assert.match(html, /4,200,000 rows/);
});
