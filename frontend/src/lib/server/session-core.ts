import { randomBytes } from 'node:crypto';
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
const globalSessions = globalThis as typeof globalThis & {
  tradegraphSessions?: Map<string, ServerSession>;
};
const sessions = (globalSessions.tradegraphSessions ??= new Map<string, ServerSession>());
export const SESSION_COOKIE = 'tradegraph_session';
export function publicSession(s: ServerSession): PublicSession {
  return { kind: 'live', role: s.role, expiresAt: s.expiresAt };
}
export function createSession(login: LoginResponse, now = Date.now()) {
  for (const [id, s] of sessions) if (s.expiresAt <= now) sessions.delete(id);
  if (sessions.size >= 1000) throw new ApiError(503, 'SESSION_CAPACITY');
  const id = randomBytes(32).toString('base64url');
  const s = {
    token: login.access_token,
    role: login.role,
    expiresAt: now + (login.expires_in - 1) * 1000,
  };
  sessions.set(id, s);
  return { id, session: publicSession(s) };
}
export function getSession(id: string | undefined, now = Date.now()) {
  if (!id || !/^[A-Za-z0-9_-]{43}$/.test(id)) return null;
  const s = sessions.get(id);
  if (!s || s.expiresAt <= now) {
    sessions.delete(id);
    return null;
  }
  return s;
}
export function deleteSession(id?: string) {
  if (id) sessions.delete(id);
}
export function authorize(s: ServerSession | null, role?: AccountRole) {
  if (!s || s.expiresAt <= Date.now()) throw new ApiError(401, 'UNAUTHORIZED');
  if (role && s.role !== role) throw new ApiError(403, 'FORBIDDEN');
  return s;
}
/** Custom header cannot be sent by a cross-origin form; CORS is never enabled. */
export function checkCsrf(request: Request, origin: string) {
  const expected = new URL(origin).origin;
  const supplied = request.headers.get('origin');
  if (
    request.headers.get('x-tradegraph-request') !== '1' ||
    (supplied !== null && supplied !== expected) ||
    request.headers.get('sec-fetch-site') === 'cross-site' ||
    (request.method !== 'GET' && supplied !== expected)
  )
    throw new ApiError(403, 'CSRF_REJECTED');
}
