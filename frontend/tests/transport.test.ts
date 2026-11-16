import test from 'node:test';
import assert from 'node:assert/strict';
import { operation } from '../src/lib/api/operations';
import { backendRequest } from '../src/lib/server/transport-core';
import { ApiError } from '../src/lib/api/errors';
import { schemas } from '../src/lib/api/schema';
import { parseWire } from '../src/lib/exact';
const health = operation('GET', ['health'], new URLSearchParams());
const response =
  (text: string, status = 200, content = 'application/json') =>
  async () =>
    new Response(text, { status, headers: { 'Content-Type': content } });
const validHealth = '{"status":"ok","dependencies":{"postgres":"up"},"trading_ready":true}';
test('transport validates response, no-store, bearer header and no token leakage', async () => {
  const value = await backendRequest(health, 'test-token', {
    baseUrl: 'http://127.0.0.1:8000',
    fetcher: async (url, init) => {
      assert.equal(String(url), 'http://127.0.0.1:8000/health');
      assert.equal(init?.cache, 'no-store');
      assert.equal(new Headers(init?.headers).get('authorization'), 'Bearer test-token');
      return new Response(validHealth, { headers: { 'Content-Type': 'application/json' } });
    },
  });
  assert.equal(JSON.stringify(value).includes('test-token'), false);
  assert.deepEqual(value, { status: 'ok', dependencies: { postgres: 'up' }, trading_ready: true });
});
for (const status of [400, 401, 403, 404, 409, 422, 429, 503, 504])
  test(`transport preserves backend ${status}`, async () => {
    await assert.rejects(
      backendRequest(health, 'test-token', {
        baseUrl: 'http://localhost:8000',
        fetcher: response('{"error":{"code":"TEST_REJECTION","message":"private text"}}', status),
      }),
      (e) => e instanceof ApiError && e.status === status && !e.message.includes('private'),
    );
  });
test('rejects malformed JSON, invalid shape, HTML, bad enums and unsafe integers', async () => {
  for (const [text, content] of [
    ['{', 'application/json'],
    ['{}', 'application/json'],
    ['<html>secret</html>', 'text/html'],
    ['{"status":"fake","dependencies":{},"trading_ready":true}', 'application/json'],
  ]) {
    await assert.rejects(
      backendRequest(health, 'test-token', {
        baseUrl: 'http://localhost:8000',
        fetcher: response(text, 200, content),
      }),
      /INVALID BACKEND RESPONSE/,
    );
  }
  assert.throws(() =>
    schemas.instruments({
      items: [{ id: 1, symbol: 'X', tick_size: 9007199254740992, lot_size: '1', is_active: true }],
    }),
  );
});
test('lossless BIGINT account and strict outgoing integer tokens', () => {
  const value = schemas.account(
    parseWire(
      '{"trader_id":"00000000-0000-4000-8000-000000000001","cash_balance":9007199254740993,"escrow_balance":0,"positions":[]}',
    ),
  );
  assert.equal(value.cash_balance, '9007199254740993');
  const op = operation(
    'POST',
    ['orders'],
    new URLSearchParams(),
    '{"instrument_id":1,"side":"BUY","price_ticks":"1","quantity":"9007199254740993"}',
    'stable-key',
  );
  assert.match(op.body!, /"quantity":9007199254740993/);
  assert.equal(op.idempotencyKey, 'stable-key');
});
test('allowlist rejects arbitrary paths, queries, bodies and malformed vectors', () => {
  for (const [segments, q] of [
    [['https:', 'evil.example'], ''],
    [['market', '..', 'book'], ''],
    [['instruments'], 'url=http://evil'],
    [['orders', 'me'], 'limit=2&limit=3'],
    [['admin', 'regimes', 'similar'], 'instrument_id=1&current=true&features=1'],
  ] as const)
    assert.throws(() => operation('GET', [...segments], new URLSearchParams(q)));
  assert.throws(() =>
    operation(
      'POST',
      ['orders'],
      new URLSearchParams(),
      '{"instrument_id":1,"side":"BUY","price_ticks":"1","quantity":"1","trader_id":"other"}',
      'key',
    ),
  );
});
test('timeout and abort report uncertain mutation outcome without retries', async () => {
  const op = operation(
    'POST',
    ['orders'],
    new URLSearchParams(),
    '{"instrument_id":1,"side":"BUY","price_ticks":"1","quantity":"1"}',
    'key',
  );
  let calls = 0;
  const fetcher: typeof fetch = async (_url, init) => {
    calls++;
    await new Promise((_resolve, reject) => {
      if (init?.signal?.aborted) reject(new Error('aborted'));
      else
        init?.signal?.addEventListener('abort', () => reject(new Error('aborted')), { once: true });
    });
    throw new Error('unreachable');
  };
  const keepAlive = setTimeout(() => {}, 100);
  try {
    await assert.rejects(
      backendRequest(op, 'test', { baseUrl: 'http://localhost:8000', timeoutMs: 10, fetcher }),
      (e) => e instanceof ApiError && e.status === 504 && e.uncertain,
    );
    await assert.rejects(
      backendRequest(op, 'test', {
        baseUrl: 'http://localhost:8000',
        signal: AbortSignal.abort(),
        fetcher,
      }),
      (e) => e instanceof ApiError && e.uncertain,
    );
    assert.equal(calls, 2);
  } finally {
    clearTimeout(keepAlive);
  }
});

test('uncertain submission survives a new adapter and never dispatches a second order', async () => {
  const { createSubmissionTracker } = await import('../src/lib/api/submission');
  const values = new Map<string, string>();
  const storage = {
    getItem: (k: string) => values.get(k) ?? null,
    setItem: (k: string, v: string) => {
      values.set(k, v);
    },
    removeItem: (k: string) => {
      values.delete(k);
    },
  };
  let calls = 0;
  await assert.rejects(
    createSubmissionTracker(storage).beginSubmission(
      'account-a',
      { instrument_id: 1, side: 'BUY', price_ticks: '1', quantity: '1' },
      async () => {
        calls++;
        throw new ApiError(504, 'TIMEOUT', true);
      },
    ),
  );
  await assert.rejects(
    createSubmissionTracker(storage).beginSubmission(
      'account-a',
      { instrument_id: 1, side: 'BUY', price_ticks: '1', quantity: '1' },
      async () => {
        calls++;
        return { order_id: '1', status: 'OPEN', accepted_at: '2026-11-16T00:00:00Z' };
      },
    ),
    /reconcile/i,
  );
  assert.equal(calls, 1);
});

test('execution history deduplicates exact IDs, scopes instruments and bounds memory', async () => {
  const { mergeExecutions } = await import('../src/lib/executions');
  const { executions } = await import('../src/lib/mock/fixtures');
  const sample = executions[0];
  const result = mergeExecutions(
    [{ ...sample, id: '9007199254740993' }],
    [
      { ...sample, id: '9007199254740993' },
      { ...sample, id: '9007199254740994' },
      { ...sample, id: '9007199254740995', instrument_id: 999 },
    ],
    sample.instrument_id,
    2,
  );
  assert.deepEqual(
    result.map((x) => x.id),
    ['9007199254740994', '9007199254740993'],
  );
});

test('durable-key reconciliation handles reload, lost response, account switch and outage', async () => {
  const { createSubmissionTracker } = await import('../src/lib/api/submission');
  const values = new Map<string, string>();
  const storage = {
    getItem: (k: string) => values.get(k) ?? null,
    setItem: (k: string, v: string) => {
      values.set(k, v);
    },
    removeItem: (k: string) => {
      values.delete(k);
    },
  };
  const order = {
    instrument_id: 1,
    side: 'BUY' as const,
    price_ticks: '100' as const,
    quantity: '1' as const,
  };
  const accepted = {
    order_id: '123' as const,
    status: 'OPEN' as const,
    accepted_at: '2026-11-16T00:00:00Z',
  };
  let originalKey = '';
  await assert.rejects(
    createSubmissionTracker(storage).beginSubmission('a', order, async (key) => {
      originalKey = key;
      throw new ApiError(504, 'TIMEOUT', true);
    }),
  );
  const reload = createSubmissionTracker(storage);
  assert.deepEqual(reload.getPendingSubmission('a')?.order, order);
  assert.equal(reload.getPendingSubmission('b'), null);
  await assert.rejects(
    reload.reconcileSubmission('a', async () => {
      throw new ApiError(503, 'UNAVAILABLE');
    }),
  );
  assert.equal(reload.getPendingSubmission('a')?.key, originalKey);
  assert.equal(
    await reload.reconcileSubmission('a', async () => ({
      trader_id: 'a',
      status: 'UNRESOLVED',
      accepted_order: null,
    })),
    null,
  );
  await assert.rejects(
    reload.retrySubmission('a', async () => {
      throw new ApiError(401, 'UNAUTHORIZED');
    }),
  );
  assert.ok(reload.getPendingSubmission('a'));
  await assert.rejects(
    reload.reconcileSubmission('a', async () => ({
      trader_id: 'b',
      status: 'ACCEPTED',
      accepted_order: accepted,
    })),
  );
  assert.ok(reload.getPendingSubmission('a'));
  assert.deepEqual(
    await reload.retrySubmission('a', async (key, payload) => {
      assert.equal(key, originalKey);
      assert.deepEqual(payload, order);
      return accepted;
    }),
    accepted,
  );
  assert.equal(reload.getPendingSubmission('a'), null);
  await assert.rejects(
    reload.beginSubmission('a', order, async () => {
      throw new ApiError(422, 'INVALID_ORDER');
    }),
  );
  assert.equal(reload.getPendingSubmission('a'), null);
  await assert.rejects(
    reload.beginSubmission('a', order, async () => {
      throw new ApiError(504, 'TIMEOUT', true);
    }),
  );
  assert.deepEqual(
    await reload.reconcileSubmission('a', async () => ({
      trader_id: 'a',
      status: 'ACCEPTED',
      accepted_order: accepted,
    })),
    accepted,
  );
  assert.equal(reload.getPendingSubmission('a'), null);
});

test('request reconciliation allowlist is exact, authenticated and read only', () => {
  const op = operation('GET', ['orders', 'requests', 'saved-key'], new URLSearchParams());
  assert.equal(op.kind, 'requestOutcome');
  assert.equal(op.authenticated, true);
  assert.equal(op.role, 'TRADER');
  for (const key of ['..', 'x?y', 'x/y', 'x%2Fy'])
    assert.throws(() => operation('GET', ['orders', 'requests', key], new URLSearchParams()));
  assert.throws(() =>
    operation('GET', ['orders', 'requests', 'key'], new URLSearchParams('trader_id=other')),
  );
  assert.throws(() => operation('POST', ['orders', 'requests', 'key'], new URLSearchParams()));
});

test('cancellation intent survives remount and clears only after owned serialized status', async () => {
  const { createCancellationTracker } = await import('../src/lib/api/submission');
  const values = new Map<string, string>();
  const storage = {
    getItem: (k: string) => values.get(k) ?? null,
    setItem: (k: string, v: string) => {
      values.set(k, v);
    },
    removeItem: (k: string) => {
      values.delete(k);
    },
  };
  const tracker = createCancellationTracker(storage);
  let calls = 0;
  await assert.rejects(
    tracker.cancel('account-secret', '1', async () => {
      calls++;
      throw new ApiError(504, 'TIMEOUT', true);
    }),
  );
  assert.equal(
    [...values.keys()].some((key) => key.includes('account-secret')),
    false,
  );
  const remount = createCancellationTracker(storage);
  assert.equal(await remount.pending('account-secret', '1'), true);
  assert.equal(await remount.pending('other', '1'), false);
  await assert.rejects(
    remount.cancel('account-secret', '1', async () => {
      calls++;
    }),
  );
  assert.equal(calls, 1);
  await assert.rejects(
    remount.reconcile('account-secret', '1', async () => {
      throw new ApiError(503, 'UNAVAILABLE');
    }),
  );
  assert.equal(await remount.pending('account-secret', '1'), true);
  await assert.rejects(
    remount.reconcile('account-secret', '1', async () => ({
      id: '1',
      trader_id: 'other',
      status: 'CANCELLED',
    })),
  );
  await remount.reconcile('account-secret', '1', async () => ({
    id: '1',
    trader_id: 'account-secret',
    status: 'CANCELLED',
  }));
  assert.equal(await remount.pending('account-secret', '1'), false);
  await remount.cancel('account-secret', '2', async () => true);
  assert.equal(await remount.pending('account-secret', '2'), false);
});

test('health accepts additive readiness and preserves existing frontend contract', () => {
  assert.deepEqual(
    schemas.health({
      status: 'ok',
      dependencies: { postgres: 'up' },
      trading_ready: true,
      readiness: {
        matching_owner: true,
        replay_complete: true,
        replayed_executions: 100,
        financial_settlement: true,
        derived_ready: false,
        reconciliation_required: false,
        closing: false,
      },
    }),
    { status: 'ok', dependencies: { postgres: 'up' }, trading_ready: true },
  );
});
