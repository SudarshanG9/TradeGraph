import type { AccountRole, LoginRequest, PreviewSession } from '../contracts';
import { ApiError } from './errors';
import { object, oneOf, role, count } from './schema';
export const sessionSchema = object({
  kind: oneOf('live'),
  role,
  expiresAt: count(0, Number.MAX_SAFE_INTEGER),
});
export async function login(request: LoginRequest, selected: AccountRole): Promise<PreviewSession> {
  const response = await fetch('/api/backend/login', {
    method: 'POST',
    credentials: 'same-origin',
    cache: 'no-store',
    headers: {
      'Content-Type': 'application/json',
      'X-TradeGraph-Request': '1',
      'X-TradeGraph-Role': selected,
    },
    body: JSON.stringify(request),
  });
  const value = await response.json();
  if (!response.ok)
    throw new ApiError(
      response.status,
      typeof value?.error?.code === 'string' ? value.error.code : 'LOGIN_FAILED',
    );
  return sessionSchema(value);
}
export async function session(): Promise<PreviewSession | null> {
  let response: Response;
  const timeout = AbortSignal.timeout(8000);
  try {
    response = await fetch('/api/session', {
      cache: 'no-store',
      credentials: 'same-origin',
      signal: timeout,
    });
  } catch {
    throw new ApiError(
      timeout.aborted ? 504 : 503,
      timeout.aborted ? 'SESSION_TIMEOUT' : 'SESSION_UNAVAILABLE',
    );
  }
  if (response.status === 401) throw new ApiError(401, 'UNAUTHORIZED');
  if (!response.ok) throw new ApiError(response.status, 'SESSION_UNAVAILABLE');
  try {
    const value: unknown = await response.json();
    return value === null ? null : sessionSchema(value);
  } catch {
    throw new ApiError(502, 'INVALID_SESSION_RESPONSE');
  }
}
export async function logout() {
  const response = await fetch('/api/session', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'X-TradeGraph-Request': '1' },
  });
  if (!response.ok) throw new ApiError(response.status, 'LOGOUT_FAILED');
}
