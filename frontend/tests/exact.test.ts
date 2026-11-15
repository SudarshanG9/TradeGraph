import test from 'node:test';
import assert from 'node:assert/strict';
import { parseWire, normalizeInteger, fmt, serializeOrder, validateOrder } from '../src/lib/exact';
import { catalog } from '../src/lib/mock/fixtures';
test('wire integers survive beyond Number.MAX_SAFE_INTEGER, including nested objects', () => {
  const parsed = parseWire(
    '{"id":9007199254740993,"n":-9223372036854775807,"items":[9223372036854775807]}',
  ) as { id: bigint; n: bigint; items: bigint[] };
  assert.equal(normalizeInteger(parsed.id), '9007199254740993');
  assert.equal(parsed.items[0], 9223372036854775807n);
  assert.equal(fmt(parsed.n), '−9,223,372,036,854,775,807');
  assert.throws(() => normalizeInteger(9007199254740992));
});
test('outgoing request preserves numeric tokens and exact multiplication', () => {
  const o = {
    instrument_id: 1,
    side: 'BUY' as const,
    price_ticks: '1' as const,
    quantity: '9007199254740993' as const,
  };
  assert.match(serializeOrder(o), /"quantity":9007199254740993/);
  assert.equal(validateOrder(o, catalog.items[0]), 9007199254740993n);
  assert.throws(
    () => validateOrder({ ...o, instrument_id: 2, quantity: '11' }, catalog.items[1]),
    /multiple of 10/,
  );
  assert.throws(() => validateOrder({ ...o, price_ticks: '9007199254740992' }, catalog.items[0]));
});

test('simulation seed serialization preserves the full signed BIGINT range', async () => {
  const { serializeSimulationStart } = await import('../src/lib/exact');
  const text = serializeSimulationStart({
    instrument_ids: [1],
    bot_count: 8,
    orders_per_second: 2,
    volatility: 'medium',
    seed: '9223372036854775807',
    max_duration_seconds: 300,
  });
  assert.match(text, /"seed":9223372036854775807/);
});
