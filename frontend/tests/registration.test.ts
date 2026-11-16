import test from 'node:test';
import assert from 'node:assert/strict';
import { operation } from '../src/lib/api/operations';
import { registrationReceipt } from '../src/lib/api/schema';
const body = {
  full_name: 'New Trader',
  email: 'new@example.test',
  password: 'valid-test-password',
};
test('registration is public, strictly allowlisted and CSRF protected', () => {
  const op = operation('POST', ['register'], new URLSearchParams(), JSON.stringify(body));
  assert.equal(op.authenticated, false);
  assert.equal(op.csrf, true);
  assert.equal(op.kind, 'register');
  for (const extra of [{ role: 'COMPLIANCE_ADMIN' }, { cash_balance: '100' }, { verified: true }])
    assert.throws(() =>
      operation('POST', ['register'], new URLSearchParams(), JSON.stringify({ ...body, ...extra })),
    );
  assert.throws(() =>
    operation(
      'POST',
      ['register'],
      new URLSearchParams(),
      JSON.stringify({ ...body, password: 'é'.repeat(40) }),
    ),
  );
});
test('registration receipt validates identity and readiness without secrets', () => {
  const registration_id = '00000000-0000-4000-8000-000000000001';
  assert.deepEqual(registrationReceipt({ registration_id, status: 'PENDING_PROVISIONING' }), {
    registration_id,
    status: 'PENDING_PROVISIONING',
  });
  for (const value of [
    { registration_id, status: 'BOGUS' },
    { registration_id: 'bad', status: 'ACTIVE' },
    { registration_id, status: 'ACTIVE', password_hash: 'secret' },
  ])
    assert.throws(() => registrationReceipt(value));
});
