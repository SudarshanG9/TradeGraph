import { NextRequest, NextResponse } from 'next/server';
import { authorize, checkCsrf, getSession, SESSION_COOKIE } from '@/lib/server/session-core';
import { liveOperation } from '@/lib/server/live-auth';
import { ApiError } from '@/lib/api/errors';
export const dynamic = 'force-dynamic';
export async function POST(request: NextRequest) {
  try {
    checkCsrf(request);
    const id = request.cookies.get(SESSION_COOKIE)?.value;
    const session = authorize(await getSession(id));
    return NextResponse.json(await liveOperation('liveTicket', id!, session), {
      headers: { 'Cache-Control': 'no-store' },
    });
  } catch (error) {
    const e = error instanceof ApiError ? error : new ApiError(503, 'LIVE_AUTH_UNAVAILABLE');
    return NextResponse.json(
      { error: { code: e.code } },
      { status: e.status, headers: { 'Cache-Control': 'no-store' } },
    );
  }
}
