import test from 'node:test';
import assert from 'node:assert/strict';
import { startPolling } from '../src/lib/polling';
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
test('polling never overlaps, pauses hidden views and aborts stale generations', async () => {
  let active = 0,
    maximum = 0,
    values = 0,
    hidden = false,
    signal: AbortSignal | undefined;
  const poll = startPolling({
    interval: 5,
    enabled: true,
    hidden: () => hidden,
    load: async (s) => {
      signal = s;
      active++;
      maximum = Math.max(maximum, active);
      await sleep(10);
      active--;
      return 1;
    },
    value: () => values++,
    error: () => assert.fail('unexpected error'),
    settled: () => {},
  });
  poll.refresh();
  poll.refresh();
  await sleep(28);
  assert.equal(maximum, 1);
  hidden = true;
  await sleep(15);
  const before = values;
  poll.refresh();
  await sleep(15);
  assert.equal(values, before);
  hidden = false;
  poll.refresh();
  poll.stop();
  assert.equal(signal?.aborted, true);
  await sleep(15);
  assert.equal(values, before);
});
test('failed polls retry with backoff and stopped generations cannot update state', async () => {
  let calls = 0,
    errors = 0,
    values = 0;
  const poll = startPolling({
    interval: 5,
    enabled: true,
    hidden: () => false,
    load: async () => {
      calls++;
      if (calls < 2) throw new Error('offline');
      return 'recovered';
    },
    value: () => values++,
    error: () => errors++,
    settled: () => {},
  });
  await sleep(24);
  poll.stop();
  assert.equal(errors, 1);
  assert.ok(values >= 1);
  assert.ok(calls <= 5);
});
