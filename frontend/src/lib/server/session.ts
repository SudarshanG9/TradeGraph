import 'server-only';
import { cookies } from 'next/headers';
import { redirect } from 'next/navigation';
import type { AccountRole } from '../contracts';
import { getSession, SESSION_COOKIE } from './session-core';
export const mockEnabled = () =>
  process.env.NODE_ENV === 'development' && process.env.TRADEGRAPH_MODE === 'mock';
export async function readSession() {
  return getSession((await cookies()).get(SESSION_COOKIE)?.value);
}
export async function requirePageRole(role: AccountRole) {
  if (mockEnabled()) return;
  const session = await readSession();
  if (!session) redirect('/auth?reason=expired');
  if (session.role !== role) redirect('/auth?reason=forbidden');
}
export function cookieOptions() {
  return {
    httpOnly: true,
    secure: new URL(process.env.APP_ORIGIN ?? 'http://127.0.0.1:3000').protocol === 'https:',
    sameSite: 'strict' as const,
    path: '/',
  };
}
