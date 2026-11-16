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
for (const status of [401, 403, 409, 422, 503])
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
