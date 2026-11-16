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
  const correlation = crypto.randomUUID();
  const started = performance.now();
  let endpoint = 'unmatched';
  let authenticatedOperation = false;
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
    endpoint = op.kind;
    authenticatedOperation = op.authenticated;
    op.requestId = correlation;
    if (op.csrf) checkCsrf(request);
    const session = op.authenticated ? authorize(await getSession(cookie), op.role) : null;
    const result = await requestBackend(op, session?.token, request.signal);
    if (op.kind === 'login') {
      const login = schemas.login(result);
      const selected = request.headers.get('x-tradegraph-role');
      if (selected && selected !== login.role) throw new ApiError(403, 'ROLE_MISMATCH');
      const created = await createSession(login);
      await deleteSession(cookie);
      const response = NextResponse.json(created.session, {
        headers: { 'Cache-Control': 'no-store', 'X-Request-ID': correlation },
      });
      response.cookies.set(SESSION_COOKIE, created.id, {
        ...cookieOptions(),
        expires: new Date(created.session.expiresAt),
      });
      return response;
    }
    return NextResponse.json(result, {
      status: ['submit', 'register'].includes(op.kind) ? 201 : 200,
      headers: { 'Cache-Control': 'no-store', 'X-Request-ID': correlation },
    });
  } catch (e) {
    const error = e instanceof ApiError ? e : new ApiError(500, 'INTERNAL_ERROR');
    console.info(
      JSON.stringify({
        request_id: correlation,
        endpoint,
        status: error.status,
        duration_ms: Math.round(performance.now() - started),
        dependency: [502, 503, 504].includes(error.status) ? 'unavailable' : 'none',
      }),
    );
    const response = NextResponse.json(
      { error: { code: error.code, uncertain: error.uncertain } },
      {
        status: error.status,
        headers: { 'Cache-Control': 'no-store', 'X-Request-ID': correlation },
      },
    );
    if (error.status === 401 && authenticatedOperation) {
      try {
        await deleteSession(cookie);
      } catch {
        return NextResponse.json({ error: { code: 'SESSION_UNAVAILABLE' } }, { status: 503 });
      }
      response.cookies.set(SESSION_COOKIE, '', { ...cookieOptions(), maxAge: 0 });
    }
    return response;
  }
}
export const GET = handle;
export const POST = handle;
