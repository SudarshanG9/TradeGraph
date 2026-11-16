import test from 'node:test';
import assert from 'node:assert/strict';
import { randomBytes } from 'node:crypto';
import { getSession, type SessionStore } from '../src/lib/server/session-core';

test('session store outage preserves credentials and recovery resolves the same session', async () => {
  let unavailable = true;
  let deletions = 0;
  const saved = { token: 'server-only', role: 'TRADER' as const, expiresAt: Date.now() + 60000 };
  const store: SessionStore = {
    create: async () => {
      throw new Error('unused');
    },
    get: async () => {
      if (unavailable) throw new Error('dependency failed');
      return saved;
    },
    delete: async () => {
      deletions++;
    },
  };
  const id = randomBytes(32).toString('base64url');
  await assert.rejects(getSession(id, Date.now(), store), {
    status: 503,
    code: 'SESSION_UNAVAILABLE',
  });
  assert.equal(deletions, 0);
  unavailable = false;
  assert.deepEqual(await getSession(id, Date.now(), store), saved);
  assert.equal(deletions, 0);
});

test('absent or invalid cookie is authoritative without contacting Redis', async () => {
  assert.equal(await getSession(undefined), null);
  assert.equal(await getSession('invalid-cookie'), null);
});
