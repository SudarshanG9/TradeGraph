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

import { createAuthController, type AuthState } from '../src/lib/auth-state';
import { ApiError } from '../src/lib/api/errors';
const saved = { kind: 'live' as const, role: 'TRADER' as const, expiresAt: Date.now() + 60000 };
test('503 remains unknown, recovery authenticates, and confirmed absence logs out', async () => {
  const states: AuthState[] = [];
  const auth = createAuthController((s) => states.push(s));
  await auth.verify(async () => {
    throw new ApiError(503, 'SESSION_UNAVAILABLE');
  });
  assert.equal(states.at(-1)?.status, 'temporarily_unavailable');
  await auth.verify(async () => saved);
  assert.deepEqual(states.at(-1), { status: 'authenticated', session: saved });
  await auth.verify(async () => null);
  assert.equal(states.at(-1)?.status, 'unauthenticated');
});
test('old verification cannot overwrite newer login or logout', async () => {
  const states: AuthState[] = [];
  const auth = createAuthController((s) => states.push(s));
  let resolve!: (s: typeof saved | null) => void;
  const pending = auth.verify(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  auth.accept(saved);
  resolve(null);
  await pending;
  assert.deepEqual(states.at(-1), { status: 'authenticated', session: saved });
  const second = auth.verify(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  await auth.logout(async () => {});
  resolve(saved);
  await second;
  assert.equal(states.at(-1)?.status, 'unauthenticated');
});
