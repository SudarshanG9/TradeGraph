'use client';
import { useState } from 'react';
import { Eye, EyeOff } from 'lucide-react';
import type { AccountRole, PreviewSession } from '@/lib/contracts';
import { usePreview } from '../preview-provider';
import { Button, Notice } from '../ui';
export function PasswordField({
  label,
  name,
  minLength = 1,
}: {
  label: string;
  name: string;
  minLength?: number;
}) {
  const [visible, setVisible] = useState(false);
  return (
    <label className="field">
      {label}
      <div className="password-field">
        <input
          name={name}
          type={visible ? 'text' : 'password'}
          required
          minLength={minLength}
          maxLength={72}
          autoComplete={name === 'password' ? 'current-password' : 'new-password'}
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
    </label>
  );
}
export function SignInForm({
  role,
  onSession,
}: {
  role: AccountRole;
  onSession: (s: PreviewSession) => void;
}) {
  const { api } = usePreview();
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
          placeholder={role === 'TRADER' ? 'alice@tradegraph.sim' : 'admin@tradegraph.sim'}
        />
      </label>
      <PasswordField name="password" label="Password" />
      {error && <Notice tone="error">{error}</Notice>}
      <Button variant="primary" type="submit" disabled={busy}>
        {busy ? 'Opening preview…' : 'Sign In · Demo'}
      </Button>
      <p className="auth-hint">
        Demo identity: {role === 'TRADER' ? 'alice@tradegraph.sim' : 'admin@tradegraph.sim'}
        <br />
        Demo password: preview-only. These are local fixture values, not backend credentials.
      </p>
    </form>
  );
}
export function SignUpForm({ role, onReturn }: { role: AccountRole; onReturn: () => void }) {
  const [error, setError] = useState(''),
    [submitted, setSubmitted] = useState(false);
  return (
    <form
      className="auth-form"
      onSubmit={(e) => {
        e.preventDefault();
        const form = new FormData(e.currentTarget);
        if (String(form.get('name')).trim().length < 2) {
          setError('Enter your full name.');
          return;
        }
        if (form.get('password') !== form.get('confirm')) {
          setError('Passwords do not match.');
          return;
        }
        setError('');
        setSubmitted(true);
        e.currentTarget.reset();
      }}
    >
      <label className="field">
        Full name
        <input name="name" autoComplete="name" required minLength={2} maxLength={120} />
      </label>
      <label className="field">
        Email address
        <input name="email" autoComplete="email" type="email" required maxLength={255} />
      </label>
      <PasswordField name="password" label="Password" minLength={8} />
      <PasswordField name="confirm" label="Confirm password" minLength={8} />
      <p className="auth-hint">
        Account type: {role === 'TRADER' ? 'Trader' : 'Administrator'}.{' '}
        {role === 'COMPLIANCE_ADMIN'
          ? 'Administrator access requires an approved invitation or administrative provisioning.'
          : 'Trader registration requires a future approved backend service.'}
      </p>
      {error && <Notice tone="error">{error}</Notice>}
      {submitted && (
        <Notice>
          Registration is not connected. No account was created and no credentials were saved.
          Contact your project administrator for a provisioned demo identity.{' '}
          <button type="button" className="link" onClick={onReturn}>
            Return to Sign In
          </button>
        </Notice>
      )}
      <Button type="submit" variant="primary">
        Preview account request
      </Button>
      <p className="auth-hint">
        UI preview only. No registration or password-reset endpoint exists.
      </p>
    </form>
  );
}
