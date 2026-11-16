import { NextRequest, NextResponse } from 'next/server';
import {
  checkCsrf,
  deleteSession,
  getSession,
  publicSession,
  SESSION_COOKIE,
} from '@/lib/server/session-core';
import { cookieOptions } from '@/lib/server/session';
import { ApiError } from '@/lib/api/errors';
export const dynamic = 'force-dynamic';
export async function GET(request: NextRequest) {
  let session;
  try {
    session = await getSession(request.cookies.get(SESSION_COOKIE)?.value);
  } catch {
    return NextResponse.json(
      { error: { code: 'SESSION_UNAVAILABLE' } },
      { status: 503, headers: { 'Cache-Control': 'no-store' } },
    );
  }
  return NextResponse.json(session ? publicSession(session) : null, {
    headers: { 'Cache-Control': 'no-store' },
  });
}
export async function POST(request: NextRequest) {
  try {
    checkCsrf(request);
  } catch (e) {
    return NextResponse.json(
      { error: { code: (e as ApiError).code } },
      { status: e instanceof ApiError ? e.status : 503 },
    );
  }
  try {
    await deleteSession(request.cookies.get(SESSION_COOKIE)?.value);
  } catch {
    return NextResponse.json(
      { error: { code: 'SESSION_UNAVAILABLE' } },
      { status: 503, headers: { 'Cache-Control': 'no-store' } },
    );
  }
  const response = NextResponse.json(null, { headers: { 'Cache-Control': 'no-store' } });
  response.cookies.set(SESSION_COOKIE, '', { ...cookieOptions(), maxAge: 0 });
  return response;
}
