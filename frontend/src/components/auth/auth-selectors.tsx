'use client';
import type { AccountRole } from '@/lib/contracts';
import { Segmented } from '../ui';
export type AuthMode = 'signin' | 'signup';
export function ModeSelector({
  value,
  onChange,
}: {
  value: AuthMode;
  onChange: (v: AuthMode) => void;
}) {
  return (
    <Segmented
      label="Authentication mode"
      value={value}
      onChange={onChange}
      options={[
        { value: 'signin', label: 'Sign In' },
        { value: 'signup', label: 'Sign Up' },
      ]}
    />
  );
}
export function RoleSelector({
  value,
  onChange,
}: {
  value: AccountRole;
  onChange: (v: AccountRole) => void;
}) {
  return (
    <Segmented
      label="Account type"
      value={value}
      onChange={onChange}
      options={[
        { value: 'TRADER', label: 'Trader' },
        { value: 'COMPLIANCE_ADMIN', label: 'Administrator' },
      ]}
    />
  );
}
