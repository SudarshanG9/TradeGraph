import test from 'node:test';
import { randomBytes } from 'node:crypto';
import type { SessionStore, ServerSession } from '../src/lib/server/session-core';
class TestStore implements SessionStore {
  values = new Map<string, ServerSession>();
  async create(s: ServerSession) {
    const id = randomBytes(32).toString('base64url');
    this.values.set(id, s);
    return id;
  }
  async get(id: string) {
    return this.values.get(id) ?? null;
  }
  async delete(id: string) {
    this.values.delete(id);
  }
}
const token = () =>
  `header.${Buffer.from(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 60 })).toString('base64url')}.signature`;

import assert from 'node:assert/strict';
import {
  createSession,
  getSession,
  deleteSession,
  publicSession,
  authorize,
  checkCsrf,
} from '../src/lib/server/session-core';
test('opaque sessions keep tokens server-side and enforce expiry, role and logout', async () => {
  const store = new TestStore();
  const created = await createSession(
    {
      access_token: token(),
      token_type: 'bearer',
      role: 'TRADER',
      expires_in: 60,
    },
    Date.now(),
    store,
  );
  try {
    assert.equal(created.id.length, 43);
    const session = (await getSession(created.id, Date.now(), store))!;
    assert.equal(JSON.stringify(publicSession(session)).includes('private-test-token'), false);
    assert.equal(authorize(session, 'TRADER').role, 'TRADER');
    assert.throws(() => authorize(session, 'COMPLIANCE_ADMIN'));
    assert.equal(await getSession(created.id + 'x', Date.now(), store), null);
    assert.equal(await getSession(created.id, Date.now() + 60000, store), null);
    assert.throws(() => authorize(null));
    await deleteSession(created.id, store);
    assert.equal(await getSession(created.id, Date.now(), store), null);
  } finally {
    await deleteSession(created.id, store);
  }
});
test('CSRF blocks forms, foreign origin, cross-site metadata and originless POST', () => {
  const origin = 'http://127.0.0.1:3000';
  for (const headers of [
    {},
    { origin },
    { origin: 'https://evil.test', 'x-tradegraph-request': '1' },
    { 'x-tradegraph-request': '1' },
    { origin, 'x-tradegraph-request': '1', 'sec-fetch-site': 'cross-site' },
  ]) {
    assert.throws(() =>
      checkCsrf(
        new Request(origin, { method: 'POST', headers: headers as Record<string, string> }),
        origin,
      ),
    );
  }
  checkCsrf(
    new Request(origin, { method: 'POST', headers: { origin, 'x-tradegraph-request': '1' } }),
    origin,
  );
  checkCsrf(
    new Request(origin, {
      headers: { 'x-tradegraph-request': '1', 'sec-fetch-site': 'same-origin' },
    }),
    origin,
  );
});

test('async shared sessions survive service recreation and fail closed on store outage', async () => {
  const store = new TestStore();
  const login = {
    access_token: token(),
    token_type: 'bearer' as const,
    role: 'TRADER' as const,
    expires_in: 60,
  };
  const first = await createSession(login, Date.now(), store);
  assert.equal((await getSession(first.id, Date.now(), store))?.token, login.access_token);
  const second = await createSession(login, Date.now(), store);
  assert.notEqual(first.id, second.id);
  assert.equal(JSON.stringify(first).includes(login.access_token), false);
  const unavailable: SessionStore = {
    create: async () => {
      throw new Error('private connection details');
    },
    get: async () => {
      throw new Error('private connection details');
    },
    delete: async () => {
      throw new Error('private connection details');
    },
  };
  await assert.rejects(getSession(first.id, Date.now(), unavailable), /SESSION UNAVAILABLE/);
  await assert.rejects(createSession(login, Date.now(), unavailable), /SESSION UNAVAILABLE/);
  await assert.rejects(deleteSession(first.id, unavailable), /SESSION UNAVAILABLE/);
  await deleteSession(first.id, store);
  assert.equal(await getSession(first.id, Date.now(), store), null);
  assert.ok(await getSession(second.id, Date.now(), store));
  await deleteSession(second.id, store);
});

test(
  'native Redis sessions share across connections, encrypt JWT and expire',
  { skip: !process.env.TRADEGRAPH_TEST_REDIS_URL },
  async () => {
    const { default: Redis } = await import('ioredis');
    const { RedisSessionStore } = await import('../src/lib/server/redis-session-store');
    const options = {
      lazyConnect: true,
      enableOfflineQueue: false,
      connectTimeout: 1000,
      maxRetriesPerRequest: 0,
    };
    const a = new Redis(process.env.TRADEGRAPH_TEST_REDIS_URL!, options);
    const b = new Redis(process.env.TRADEGRAPH_TEST_REDIS_URL!, options);
    const key = randomBytes(32);
    const first = new RedisSessionStore(a, key),
      restarted = new RedisSessionStore(b, key);
    let id = '';
    try {
      const session = { token: token(), role: 'TRADER' as const, expiresAt: Date.now() + 250 };
      id = await first.create(session);
      assert.deepEqual(await restarted.get(id), session);
      const encrypted = await a.get('tradegraph:frontend:session:' + id);
      assert.equal(encrypted!.includes(session.token), false);
      assert.ok((await a.pttl('tradegraph:frontend:session:' + id)) > 0);
      await new Promise((resolve) => setTimeout(resolve, 300));
      assert.equal(await restarted.get(id), null);
      id = await first.create({ ...session, expiresAt: Date.now() + 10000 });
      await restarted.delete(id);
      assert.equal(await first.get(id), null);
    } finally {
      if (id && a.status === 'ready') await a.del('tradegraph:frontend:session:' + id);
      a.disconnect();
      b.disconnect();
    }
  },
);

test('production origin requires explicit HTTPS with only an explicit local-test exception', async () => {
  const { applicationOrigin } = await import('../src/lib/server/app-origin');
  assert.throws(() => applicationOrigin({ NODE_ENV: 'production' }));
  for (const APP_ORIGIN of [
    'http://exchange.test',
    'https://u:p@exchange.test',
    'https://exchange.test/path',
    'https://exchange.test?',
    'https://exchange.test#',
    'not a url',
    ' https://exchange.test',
    'http://127.0.0.1:3000',
  ])
    assert.throws(() => applicationOrigin({ NODE_ENV: 'production', APP_ORIGIN }));
  assert.equal(
    applicationOrigin({ NODE_ENV: 'production', APP_ORIGIN: 'https://exchange.test/' }),
    'https://exchange.test',
  );
  assert.equal(applicationOrigin({ NODE_ENV: 'development' }), 'http://127.0.0.1:3000');
  assert.equal(
    applicationOrigin({
      NODE_ENV: 'production',
      APP_ORIGIN: 'http://127.0.0.1:3000',
      ALLOW_INSECURE_LOOPBACK_ORIGIN: 'true',
    }),
    'http://127.0.0.1:3000',
  );
  assert.throws(() =>
    applicationOrigin({
      NODE_ENV: 'production',
      APP_ORIGIN: 'http://exchange.test',
      ALLOW_INSECURE_LOOPBACK_ORIGIN: 'true',
    }),
  );
});

test(
  'native Redis connection failure rejects a valid session without fallback',
  { skip: !process.env.TRADEGRAPH_TEST_REDIS_URL },
  async () => {
    const { default: Redis } = await import('ioredis');
    const { RedisSessionStore } = await import('../src/lib/server/redis-session-store');
    const client = new Redis('redis://127.0.0.1:1/0', {
      lazyConnect: true,
      enableOfflineQueue: false,
      connectTimeout: 100,
      maxRetriesPerRequest: 0,
      retryStrategy: () => null,
    });
    client.on('error', () => {});
    const store = new RedisSessionStore(client, randomBytes(32));
    try {
      await assert.rejects(
        getSession(randomBytes(32).toString('base64url'), Date.now(), store),
        /SESSION UNAVAILABLE/,
      );
    } finally {
      client.disconnect();
    }
  },
);

test('CSRF diagnoses each rejection without allowing an alternate development host', () => {
  const origin = 'http://127.0.0.1:3000';
  for (const [headers, code] of [
    [{ origin }, 'CSRF_HEADER_REQUIRED'],
    [{ 'x-tradegraph-request': '1' }, 'CSRF_ORIGIN_REQUIRED'],
    [{ origin: 'http://localhost:3000', 'x-tradegraph-request': '1' }, 'CANONICAL_ORIGIN_REQUIRED'],
    [{ origin: 'https://evil.test', 'x-tradegraph-request': '1' }, 'CSRF_FOREIGN_ORIGIN'],
    [{ origin, 'x-tradegraph-request': '1', 'sec-fetch-site': 'cross-site' }, 'CSRF_CROSS_SITE'],
  ] as const) {
    assert.throws(() => checkCsrf(new Request(origin, { method: 'POST', headers }), origin), {
      status: 403,
      code,
    });
  }
  assert.throws(() => checkCsrf(new Request(origin, { method: 'POST' }), 'invalid'), {
    status: 503,
    code: 'APP_ORIGIN_CONFIGURATION_INVALID',
  });
});
