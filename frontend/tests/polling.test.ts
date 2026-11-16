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

test('manual retries while pending coalesce into one trailing request and await fresh result', async () => {
  let release!: () => void;
  let calls = 0;
  const values: number[] = [];
  const poll = startPolling({
    interval: 0,
    enabled: true,
    hidden: () => false,
    load: async () => {
      const n = ++calls;
      if (n === 1)
        await new Promise<void>((r) => {
          release = r;
        });
      return n;
    },
    value: (v) => values.push(v),
    error: () => assert.fail('unexpected error'),
    settled: () => {},
  });
  const retry = poll.refresh();
  const another = poll.refresh();
  assert.equal(calls, 1);
  release();
  assert.equal(await retry, true);
  assert.equal(await another, true);
  assert.deepEqual(values, [1, 2]);
  assert.equal(calls, 2);
  poll.stop();
});
test('scope cancellation suppresses old success and resolves queued refresh', async () => {
  let release!: (v: string) => void;
  const values: string[] = [];
  const poll = startPolling({
    interval: 0,
    enabled: true,
    hidden: () => false,
    load: () =>
      new Promise<string>((r) => {
        release = r;
      }),
    value: (v) => values.push(v),
    error: () => {},
    settled: () => {},
  });
  const retry = poll.refresh();
  poll.stop();
  assert.equal(await retry, false);
  release('old account');
  await sleep(1);
  assert.deepEqual(values, []);
});
