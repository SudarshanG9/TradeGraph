import 'server-only';
import { createHash } from 'node:crypto';
import { requestBackend } from './transport';
import type { ServerSession } from './session-core';
export async function liveOperation(
  kind: 'liveTicket' | 'liveRevoke',
  id: string,
  session: ServerSession,
) {
  return requestBackend(
    {
      path: kind === 'liveTicket' ? '/live/ticket' : '/live/revoke',
      method: 'POST',
      kind,
      authenticated: true,
      csrf: true,
      body: JSON.stringify({ session_key: createHash('sha256').update(id).digest('hex') }),
    },
    session.token,
  );
}
