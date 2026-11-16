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
export function GET(request: NextRequest) {
  const session = getSession(request.cookies.get(SESSION_COOKIE)?.value);
  return NextResponse.json(session ? publicSession(session) : null, {
    headers: { 'Cache-Control': 'no-store' },
  });
}
export function POST(request: NextRequest) {
  try {
    checkCsrf(request, process.env.APP_ORIGIN ?? 'http://127.0.0.1:3000');
  } catch (e) {
    return NextResponse.json({ error: { code: (e as ApiError).code } }, { status: 403 });
  }
  deleteSession(request.cookies.get(SESSION_COOKIE)?.value);
  const response = NextResponse.json(null, { headers: { 'Cache-Control': 'no-store' } });
  response.cookies.set(SESSION_COOKIE, '', { ...cookieOptions(), maxAge: 0 });
  return response;
}
