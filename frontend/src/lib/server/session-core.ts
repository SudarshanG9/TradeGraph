import { applicationOrigin, wrongDevelopmentOrigin } from './app-origin';
import { sharedSessionStore } from './redis-session-store';
import type { AccountRole, LoginResponse } from '../contracts';
import { ApiError } from '../api/errors';
export interface ServerSession {
  token: string;
  role: AccountRole;
  expiresAt: number;
}
export interface PublicSession {
  kind: 'live';
  role: AccountRole;
  expiresAt: number;
}
export interface SessionStore {
  create(session: ServerSession): Promise<string>;
  get(id: string): Promise<ServerSession | null>;
  delete(id: string): Promise<void>;
}
export const SESSION_COOKIE = 'tradegraph_session';
export function publicSession(s: ServerSession): PublicSession {
  return { kind: 'live', role: s.role, expiresAt: s.expiresAt };
}
const validId = (id: string | undefined): id is string => !!id && /^[A-Za-z0-9_-]{43}$/.test(id);
async function stored<T>(action: () => Promise<T>): Promise<T> {
  try {
    return await action();
  } catch (e) {
    if (e instanceof ApiError) throw e;
    throw new ApiError(503, 'SESSION_UNAVAILABLE');
  }
}
export async function createSession(login: LoginResponse, now = Date.now(), store?: SessionStore) {
  let expiration: number;
  try {
    expiration =
      JSON.parse(Buffer.from(login.access_token.split('.')[1], 'base64url').toString()).exp * 1000;
  } catch {
    throw new ApiError(502, 'INVALID_BACKEND_RESPONSE');
  }
  const session: ServerSession = {
    token: login.access_token,
    role: login.role,
    expiresAt: Math.min(expiration, now + (login.expires_in - 1) * 1000),
  };
  if (!Number.isFinite(session.expiresAt) || session.expiresAt <= now)
    throw new ApiError(401, 'UNAUTHORIZED');
  const id = await stored(() => (store ?? sharedSessionStore()).create(session));
  return { id, session: publicSession(session) };
}
export async function getSession(id: string | undefined, now = Date.now(), store?: SessionStore) {
  if (!validId(id)) return null;
  const selected = store ?? sharedSessionStore();
  const session = await stored(() => selected.get(id));
  if (!session) return null;
  if (
    !['TRADER', 'COMPLIANCE_ADMIN'].includes(session.role) ||
    typeof session.token !== 'string' ||
    !Number.isFinite(session.expiresAt) ||
    session.expiresAt <= now
  ) {
    await stored(() => selected.delete(id));
    return null;
  }
  return session;
}
export async function deleteSession(id?: string, store?: SessionStore) {
  if (validId(id)) await stored(() => (store ?? sharedSessionStore()).delete(id));
}
export function authorize(s: ServerSession | null, role?: AccountRole) {
  if (!s || s.expiresAt <= Date.now()) throw new ApiError(401, 'UNAUTHORIZED');
  if (role && s.role !== role) throw new ApiError(403, 'FORBIDDEN');
  return s;
}
/** Custom header cannot be sent by a cross-origin form; CORS is never enabled. */
export function checkCsrf(request: Request, origin: string = applicationOrigin()) {
  const expected = applicationOrigin({ APP_ORIGIN: origin });
  const supplied = request.headers.get('origin');
  if (request.headers.get('sec-fetch-site') === 'cross-site')
    throw new ApiError(403, 'CSRF_CROSS_SITE');
  if (request.headers.get('x-tradegraph-request') !== '1')
    throw new ApiError(403, 'CSRF_HEADER_REQUIRED');
  if (supplied === null && request.method !== 'GET')
    throw new ApiError(403, 'CSRF_ORIGIN_REQUIRED');
  if (supplied !== null && supplied !== expected)
    throw new ApiError(
      403,
      wrongDevelopmentOrigin(supplied, expected)
        ? 'CANONICAL_ORIGIN_REQUIRED'
        : 'CSRF_FOREIGN_ORIGIN',
    );
}
