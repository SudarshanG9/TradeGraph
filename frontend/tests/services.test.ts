import test from 'node:test';
import assert from 'node:assert/strict';
import { createMockServices } from '../src/lib/services';
import type { FixtureState, Outcome, PreviewSession } from '../src/lib/contracts';
const setup = () => {
  let session: PreviewSession | null = {
    role: 'TRADER',
    kind: 'mock-preview',
    expiresAt: Date.now() + 100000,
  };
  let fixture: FixtureState = 'populated';
  let outcome: Outcome = 'accepted';
  return {
    api: createMockServices(
      () => session,
      () => fixture,
      () => outcome,
    ),
    setRole: (role: 'TRADER' | 'COMPLIANCE_ADMIN') => {
      session = { role, kind: 'mock-preview', expiresAt: Date.now() + 100000 };
    },
    expire: () => {
      session = null;
    },
    fixture: (s: FixtureState) => {
      fixture = s;
    },
    outcome: (s: Outcome) => {
      outcome = s;
    },
  };
};
test('role guards, expiry, credential mismatch and no registration service', async () => {
  const s = setup();
  await assert.rejects(s.api.health.get(), /ROLE_MISMATCH/);
  await assert.rejects(
    s.api.auth.login({ email: 'admin@tradegraph.sim', password: 'preview-only' }, 'TRADER'),
    /mismatch/,
  );
  s.expire();
  await assert.rejects(s.api.orders.list(), /SESSION_EXPIRED/);
  assert.equal('register' in s.api.auth, false);
});
test('cursor pagination, terminal cancellation, and large balances', async () => {
  const s = setup();
  const p = await s.api.orders.list({ limit: 5 });
  assert.ok(p.next_before_id);
  const next = await s.api.orders.list({ limit: 5, before_id: p.next_before_id! });
  assert.ok(next.items.every((x) => BigInt(x.id) < BigInt(p.next_before_id!)));
  assert.equal(next.next_before_id, null);
  await assert.rejects(s.api.orders.cancel('8830'), /TERMINAL/);
  await s.api.orders.cancel('8841');
  const row = (await s.api.orders.list()).items.find((x) => x.id === '8841')!;
  assert.equal(row.status, 'CANCELLED');
  assert.equal(row.filled_quantity, '6');
  s.fixture('large');
  assert.equal((await s.api.account.get()).cash_balance, '9007199254740993');
});
test('market data is symbol-scoped and inclusive band volumes use executions', async () => {
  const s = setup();
  const r = await s.api.market.trades('ACME', { limit: 100 });
  assert.ok(r.items.every((t) => t.instrument_id === 1));
  const a = await s.api.market.analytics('ACME', '100', '100');
  assert.equal(
    a.band_volume,
    String(
      r.items.filter((x) => x.price_ticks === '100').reduce((n, x) => n + BigInt(x.quantity), 0n),
    ),
  );
  s.fixture('empty');
  assert.equal((await s.api.market.analytics('ACME', '0', '999')).vwap_ticks, null);
});
test('simulator validates bounds, STOPPING is not success, and ERROR blocks restart', async () => {
  const s = setup();
  s.setRole('COMPLIANCE_ADMIN');
  const cfg = {
    instrument_ids: [1],
    bot_count: 8,
    orders_per_second: 2,
    volatility: 'medium' as const,
    seed: '9223372036854775807' as const,
    max_duration_seconds: 300,
  };
  await assert.rejects(s.api.simulator.start({ ...cfg, bot_count: 9 }), /bounds/);
  assert.equal((await s.api.simulator.start(cfg)).state, 'RUNNING');
  s.outcome('unknown');
  assert.equal((await s.api.simulator.stop()).state, 'ERROR');
  await assert.rejects(s.api.simulator.start(cfg), /conflict/);
});

test('an empty active catalog never creates a fallback trading instrument', async () => {
  const s = setup();
  s.fixture('no-instruments');
  assert.deepEqual(await s.api.instruments.list(), { items: [] });
  await assert.rejects(s.api.market.book('ACME'), /NOT_FOUND/);
  await assert.rejects(
    s.api.orders.submit({ instrument_id: 1, side: 'BUY', price_ticks: '100', quantity: '1' }),
    /NOT_FOUND/,
  );
});
test('optimizer keeps all nested conditions aligned with submitted bounds', async () => {
  const s = setup();
  s.setRole('COMPLIANCE_ADMIN');
  const result = await s.api.optimizer.compare('price_band', 2, '200', '230');
  const html = JSON.stringify(result.plans);
  assert.match(html, /BETWEEN 200 AND 230/);
  assert.doesNotMatch(html, /BETWEEN 95 AND 105/);
  const recent = await s.api.optimizer.compare('recent_executions', 1, '95', '105');
  assert.equal(
    recent.plans.automatic['Execution Time'],
    recent.plans.forced_sequential['Execution Time'],
  );
});

test('administrative search validates vectors, missing observations and bounded queries', async () => {
  const s = setup();
  s.setRole('COMPLIANCE_ADMIN');
  await assert.rejects(
    s.api.regimes.similar({ instrument_id: 1, k: 10, features: [0, 0, 0, 0, 0, 0] }),
    /nonzero/,
  );
  await assert.rejects(s.api.regimes.similar({ instrument_id: 1, k: 0, current: true }), /limit/);
  s.fixture('empty');
  await assert.rejects(
    s.api.regimes.similar({ instrument_id: 1, k: 10, current: true }),
    /NO_MARKET_OBSERVATIONS/,
  );
  assert.deepEqual(
    await s.api.regimes.similar({ instrument_id: 1, k: 10, features: [1, 0, 0, 0, 0, 0] }),
    { matches: [] },
  );
  await assert.rejects(s.api.disclosures.search(''), /query/);
});
test('mock order outcomes distinguish accepted, partial, filled, rejected and unknown', async () => {
  const s = setup();
  const order = {
    instrument_id: 1,
    side: 'BUY' as const,
    price_ticks: '100' as const,
    quantity: '10' as const,
  };
  for (const [outcome, status] of [
    ['accepted', 'OPEN'],
    ['partial', 'PARTIAL'],
    ['filled', 'FILLED'],
  ] as const) {
    s.outcome(outcome);
    const result = await s.api.orders.submit(order);
    assert.equal(result.status, 'OPEN');
    const row = (await s.api.orders.list()).items.find((o) => o.id === result.order_id)!;
    assert.equal(row.status, status);
  }
  s.outcome('rejected');
  await assert.rejects(s.api.orders.submit(order), /rejected/);
  s.outcome('unknown');
  await assert.rejects(s.api.orders.submit(order), /Unknown mock outcome/);
});
