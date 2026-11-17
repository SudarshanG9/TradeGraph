'use client';
import { useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import type { AccountRole, PreviewSession } from '@/lib/contracts';
import { usePreview } from '../preview-provider';
import * as liveAuth from '@/lib/api/auth-client';
import type { RegistrationReceipt } from '@/lib/contracts';
import { Button, Notice } from '../ui';
export function PasswordField({
  label,
  name,
  minLength = 1,
  autoComplete = 'current-password',
}: {
  label: string;
  name: string;
  minLength?: number;
  autoComplete?: 'current-password' | 'new-password';
}) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="field">
      <label htmlFor={`auth-${name}`}>{label}</label>
      <div className="password-field">
        <input
          name={name}
          id={`auth-${name}`}
          type={visible ? 'text' : 'password'}
          required
          minLength={minLength}
          maxLength={72}
          autoComplete={autoComplete}
        />
        <button
          type="button"
          aria-label={`${visible ? 'Hide' : 'Show'} ${label.toLowerCase()}`}
          aria-pressed={visible}
          onClick={() => setVisible(!visible)}
        >
          {visible ? <EyeOff size={16} /> : <Eye size={16} />}
        </button>
      </div>
    </div>
  );
}
export function SignInForm({
  role,
  onSession,
}: {
  role: AccountRole;
  onSession: (s: PreviewSession) => void;
}) {
  const { api, mock } = usePreview();
  const [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  return (
    <form
      className="auth-form"
      onSubmit={async (e) => {
        e.preventDefault();
        setError('');
        const data = new FormData(e.currentTarget);
        setBusy(true);
        try {
          onSession(
            await api.auth.login(
              { email: String(data.get('email')), password: String(data.get('password')) },
              role,
            ),
          );
        } catch (e) {
          setError((e as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <label className="field">
        Email address
        <input
          type="email"
          name="email"
          required
          maxLength={255}
          autoComplete="username"
          placeholder={
            mock
              ? role === 'TRADER'
                ? 'alice@tradegraph.sim'
                : 'admin@tradegraph.sim'
              : role === 'TRADER'
                ? 'alice@tradegraph.test'
                : 'admin@tradegraph.test'
          }
        />
      </label>
      <PasswordField name="password" label="Password" />
      {error && <Notice tone="error">{error}</Notice>}
      <Button variant="primary" type="submit" disabled={busy}>
        {busy ? 'Signing in…' : mock ? 'Sign In · Demo' : 'Sign In'}
      </Button>
      {mock && (
        <p className="auth-hint">
          Demo identity: {role === 'TRADER' ? 'alice@tradegraph.sim' : 'admin@tradegraph.sim'}
          <br />
          Demo password: preview-only. These are local fixture values, not backend credentials.
        </p>
      )}
    </form>
  );
}
export function SignUpForm({ role, onReturn }: { role: AccountRole; onReturn: () => void }) {
  const { mock } = usePreview();
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [receipt, setReceipt] = useState<RegistrationReceipt | null>(null);
  if (role === 'COMPLIANCE_ADMIN')
    return (
      <Notice>
        Administrator accounts are created by the operator. Public signup is for traders.{' '}
        <button className="link" onClick={onReturn}>
          Return to Sign In
        </button>
      </Notice>
    );
  return (
    <form
      className="auth-form"
      onSubmit={async (e) => {
        e.preventDefault();
        const form = new FormData(e.currentTarget);
        const password = String(form.get('password'));
        setError('');
        if (password !== form.get('confirm')) {
          setError('Passwords do not match.');
          return;
        }
        if (new TextEncoder().encode(password).length > 72) {
          setError('Password must fit within 72 UTF-8 bytes.');
          return;
        }
        if (mock) {
          setError('Registration requires the live application. No account was created.');
          return;
        }
        setBusy(true);
        try {
          setReceipt(
            await liveAuth.register({
              full_name: String(form.get('name')).trim(),
              email: String(form.get('email')).trim().toLowerCase(),
              password,
            }),
          );
        } catch (error) {
          setError((error as Error).message);
        } finally {
          setBusy(false);
        }
      }}
    >
      <label className="field">
        Full name
        <input name="name" autoComplete="name" required minLength={2} maxLength={150} />
      </label>
      <label className="field">
        Email address
        <input name="email" autoComplete="email" type="email" required maxLength={255} />
      </label>
      <PasswordField name="password" label="Password" minLength={12} autoComplete="new-password" />
      <PasswordField
        name="confirm"
        label="Confirm password"
        minLength={12}
        autoComplete="new-password"
      />
      <p className="auth-hint">
        Account type: Trader. Account setup is automatic; no approval is required.
      </p>
      {error && <Notice tone="error">{error}</Notice>}
      {receipt && (
        <Notice tone={receipt.status === 'ACTIVE' ? 'success' : 'info'}>
          {receipt.status === 'ACTIVE'
            ? 'Your account is active. You can sign in.'
            : receipt.status === 'PENDING_VERIFICATION'
              ? 'Account created. Automatic setup is in progress. You can sign in shortly.'
              : 'Account created. Automatic setup is in progress. You can sign in shortly.'}{' '}
          <button type="button" className="link" onClick={onReturn}>
            Return to Sign In
          </button>
        </Notice>
      )}
      <Button type="submit" variant="primary" disabled={busy || !!receipt}>
        {busy ? 'Creating account…' : 'Create trader account'}
      </Button>
    </form>
  );
}
