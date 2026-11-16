import test from 'node:test';
import assert from 'node:assert/strict';
import { createLiveClient, type LiveSocket } from '../src/lib/live/client';
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
class Socket implements LiveSocket {
  readyState = 1;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((e: { data: string }) => void) | null = null;
  sent: string[] = [];
  closed = false;
  send(s: string) {
    this.sent.push(s);
  }
  close() {
    this.closed = true;
  }
  emit(type: string, sequence: number, extra = {}) {
    this.onmessage?.({
      data: JSON.stringify({
        schema_version: 1,
        type,
        epoch: 'owner',
        sequence,
        published_at: new Date().toISOString(),
        ...extra,
      }),
    });
  }
}
test('one connection serves multiple subscribers, rejects stale versions and detects gaps', async () => {
  const sockets: Socket[] = [];
  const events: string[] = [];
  const states: string[] = [];
  const live = createLiveClient({
    ticket: async () => ({ ticket: 'temporary', path: '/live/ws' }),
    socket: () => {
      const s = new Socket();
      sockets.push(s);
      return s;
    },
    state: (s) => states.push(s),
    event: (e) => events.push(e.type),
    retryMs: 1,
    random: () => 0.5,
  });
  let subscribers = 0;
  live.subscribe(() => subscribers++);
  live.subscribe(() => subscribers++);
  live.instruments([1]);
  live.start();
  live.start();
  await sleep(1);
  assert.equal(sockets.length, 1);
  const ws = sockets[0];
  ws.onopen?.();
  ws.emit('resync.required', 1);
  assert.equal(states.at(-1), 'resyncing');
  live.synchronized();
  assert.equal(states.at(-1), 'live');
  ws.emit('book.changed', 2, { instrument_id: 1, version: 3 });
  ws.emit('book.changed', 3, { instrument_id: 1, version: 2 });
  ws.emit('book.changed', 2, { instrument_id: 1, version: 5 });
  assert.deepEqual(events, ['resync.required', 'book.changed']);
  assert.equal(subscribers, 4);
  ws.emit('account.changed', 5);
  assert.equal(live.diagnostics.gaps, 1);
  assert.equal(states.at(-1), 'resyncing');
  live.instruments([2]);
  ws.emit('book.changed', 6, { instrument_id: 1, version: 6 });
  assert.equal(events.at(-1), 'account.changed');
  ws.onclose?.();
  await sleep(5);
  assert.equal(sockets.length, 2);
  assert.equal(ws.closed, true);
  live.stop();
  assert.equal(sockets[1].closed, true);
});
test('logout while ticket pending prevents a socket and repeated failures use bounded reconnect', async () => {
  let resolve!: (v: { ticket: string; path: string }) => void;
  let calls = 0;
  const live = createLiveClient({
    ticket: () =>
      new Promise((r) => {
        resolve = r;
      }),
    socket: () => {
      calls++;
      return new Socket();
    },
    state: () => {},
    event: () => {},
  });
  live.start();
  live.stop();
  resolve({ ticket: 'temporary', path: '/live/ws' });
  await sleep(1);
  assert.equal(calls, 0);
  let attempts = 0;
  const failing = createLiveClient({
    ticket: async () => {
      attempts++;
      throw new Error('offline');
    },
    socket: () => new Socket(),
    state: () => {},
    event: () => {},
    retryMs: 2,
    random: () => 0.5,
  });
  failing.start();
  await sleep(18);
  failing.stop();
  assert.ok(attempts >= 2 && attempts <= 5);
});
