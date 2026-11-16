import test from 'node:test';
import assert from 'node:assert/strict';
import {
  createSession,
  getSession,
  deleteSession,
  publicSession,
  authorize,
  checkCsrf,
} from '../src/lib/server/session-core';
test('opaque sessions keep tokens server-side and enforce expiry, role and logout', () => {
  const created = createSession({
    access_token: 'private-test-token',
    token_type: 'bearer',
    role: 'TRADER',
    expires_in: 60,
  });
  try {
    assert.equal(created.id.length, 43);
    const session = getSession(created.id)!;
    assert.equal(JSON.stringify(publicSession(session)).includes('private-test-token'), false);
    assert.equal(authorize(session, 'TRADER').role, 'TRADER');
    assert.throws(() => authorize(session, 'COMPLIANCE_ADMIN'));
    assert.equal(getSession(created.id + 'x'), null);
    assert.equal(getSession(created.id, Date.now() + 60000), null);
    assert.throws(() => authorize(null));
    deleteSession(created.id);
    assert.equal(getSession(created.id), null);
  } finally {
    deleteSession(created.id);
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
