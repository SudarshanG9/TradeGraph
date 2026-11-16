import { NextRequest, NextResponse } from 'next/server';
import { operation } from '@/lib/api/operations';
import { ApiError } from '@/lib/api/errors';
import { schemas } from '@/lib/api/schema';
import { requestBackend } from '@/lib/server/transport';
import {
  authorize,
  checkCsrf,
  createSession,
  deleteSession,
  getSession,
  SESSION_COOKIE,
} from '@/lib/server/session-core';
import { cookieOptions } from '@/lib/server/session';
export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';
async function handle(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const cookie = request.cookies.get(SESSION_COOKIE)?.value;
  try {
    const { path } = await context.params;
    if (Number(request.headers.get('content-length') ?? 0) > 8192)
      throw new ApiError(413, 'REQUEST_TOO_LARGE');
    const raw = request.method === 'POST' ? await request.text() : undefined;
    if (raw && raw.length > 8192) throw new ApiError(413, 'REQUEST_TOO_LARGE');
    if (
      request.method === 'POST' &&
      !request.headers.get('content-type')?.startsWith('application/json')
    )
      throw new ApiError(415, 'JSON_REQUIRED');
    const op = operation(
      request.method,
      path,
      request.nextUrl.searchParams,
      raw,
      request.headers.get('idempotency-key') ?? undefined,
    );
    if (op.csrf) checkCsrf(request, process.env.APP_ORIGIN ?? 'http://127.0.0.1:3000');
    const session = op.authenticated ? authorize(getSession(cookie), op.role) : null;
    const result = await requestBackend(op, session?.token, request.signal);
    if (op.kind === 'login') {
      const login = schemas.login(result);
      const selected = request.headers.get('x-tradegraph-role');
      if (selected && selected !== login.role) throw new ApiError(403, 'ROLE_MISMATCH');
      deleteSession(cookie);
      const created = createSession(login);
      const response = NextResponse.json(created.session, {
        headers: { 'Cache-Control': 'no-store' },
      });
      response.cookies.set(SESSION_COOKIE, created.id, {
        ...cookieOptions(),
        expires: new Date(created.session.expiresAt),
      });
      return response;
    }
    return NextResponse.json(result, { headers: { 'Cache-Control': 'no-store' } });
  } catch (e) {
    const error = e instanceof ApiError ? e : new ApiError(500, 'INTERNAL_ERROR');
    const response = NextResponse.json(
      { error: { code: error.code, uncertain: error.uncertain } },
      { status: error.status, headers: { 'Cache-Control': 'no-store' } },
    );
    if (error.status === 401) {
      deleteSession(cookie);
      response.cookies.set(SESSION_COOKIE, '', { ...cookieOptions(), maxAge: 0 });
    }
    return response;
  }
}
export const GET = handle;
export const POST = handle;
