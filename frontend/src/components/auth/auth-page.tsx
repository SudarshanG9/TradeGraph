'use client';
import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import type { AccountRole, PreviewSession } from '@/lib/contracts';
import { homeFor } from '@/lib/exact';
import { usePreview } from '../preview-provider';
import { Notice } from '../ui';
import { AuthContainer } from './auth-container';
import { ModeSelector, RoleSelector, type AuthMode } from './auth-selectors';
import { SignInForm, SignUpForm } from './auth-form';
export function AuthPage() {
  const [mode, setMode] = useState<AuthMode>('signin'),
    [role, setRole] = useState<AccountRole>('TRADER'),
    [expired, setExpired] = useState(false);
  const { api, signIn, mock } = usePreview(),
    router = useRouter();
  useEffect(() => {
    setExpired(new URLSearchParams(window.location.search).get('reason') === 'expired');
  }, []);
  const enter = (s: PreviewSession) => {
    signIn(s);
    router.push(homeFor(s.role));
  };
  return (
    <AuthContainer
      title={mode === 'signin' ? 'Sign in' : 'Sign up'}
      footer={
        mock ? (
          <div className="auth-footer">
            <p className="eyebrow">Mock role preview — for review only</p>
            <div className="toolbar">
              <button className="link positive" onClick={() => enter(api.auth.preview('TRADER'))}>
                View as Trader →
              </button>
              <button className="link" onClick={() => enter(api.auth.preview('COMPLIANCE_ADMIN'))}>
                View as Compliance Admin →
              </button>
            </div>
          </div>
        ) : (
          <p className="auth-hint">
            Sign in with an existing provisioned account. Account registration is unavailable.
          </p>
        )
      }
    >
      <ModeSelector value={mode} onChange={setMode} />
      <RoleSelector value={role} onChange={setRole} />
      {expired && (
        <div className="auth-feedback">
          <Notice tone="warning">
            Session expired or access unavailable. Sign in with an authorized account to continue.
          </Notice>
        </div>
      )}
      {mode === 'signin' ? (
        <SignInForm key={role} role={role} onSession={enter} />
      ) : (
        <SignUpForm key={role} role={role} onReturn={() => setMode('signin')} />
      )}
    </AuthContainer>
  );
}
