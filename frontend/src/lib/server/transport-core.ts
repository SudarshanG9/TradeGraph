import { parseWire } from '../exact';
import { ApiError } from '../api/errors';
import type { Operation } from '../api/operations';
import { schemas } from '../api/schema';

/** Server transport core; imported by server-only wrapper and isolated transport tests. */
export async function backendRequest(
  op: Operation,
  token: string | undefined,
  options: {
    baseUrl: string;
    signal?: AbortSignal;
    timeoutMs?: number;
    fetcher?: typeof fetch;
  },
) {
  const base = new URL(options.baseUrl);
  if (
    !['http:', 'https:'].includes(base.protocol) ||
    base.username ||
    base.password ||
    base.search ||
    base.hash ||
    base.pathname !== '/'
  )
    throw new ApiError(503, 'BACKEND_CONFIGURATION_INVALID');
  if (op.authenticated && !token) throw new ApiError(401, 'UNAUTHORIZED');
  const timeout = AbortSignal.timeout(options.timeoutMs ?? 15000);
  const signal = options.signal ? AbortSignal.any([timeout, options.signal]) : timeout;
  let response: Response;
  let text: string;
  try {
    response = await (options.fetcher ?? fetch)(new URL(op.path, base), {
      method: op.method,
      body: op.body,
      redirect: 'error',
      cache: 'no-store',
      signal,
      headers: {
        Accept: 'application/json',
        ...(op.body ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(op.idempotencyKey ? { 'Idempotency-Key': op.idempotencyKey } : {}),
      },
    });
    text = await response.text();
  } catch {
    throw new ApiError(
      timeout.aborted ? 504 : 502,
      timeout.aborted ? 'BACKEND_TIMEOUT' : 'BACKEND_UNAVAILABLE',
      op.method === 'POST' && op.kind !== 'login',
    );
  }
  if (!response.headers.get('content-type')?.toLowerCase().startsWith('application/json'))
    throw new ApiError(
      502,
      'INVALID_BACKEND_RESPONSE',
      op.method === 'POST' && op.kind !== 'login',
    );
  let value: unknown;
  try {
    value = parseWire(text);
  } catch {
    throw new ApiError(
      502,
      'INVALID_BACKEND_RESPONSE',
      op.method === 'POST' && op.kind !== 'login',
    );
  }
  if (!response.ok) {
    const code =
      value &&
      typeof value === 'object' &&
      'error' in value &&
      value.error &&
      typeof value.error === 'object' &&
      'code' in value.error
        ? value.error.code
        : '';
    // Forward machine codes only, never arbitrary upstream text, tracebacks or HTML.
    throw new ApiError(
      response.status,
      typeof code === 'string' && /^[A-Z][A-Z0-9_]{0,100}$/.test(code) ? code : 'BACKEND_ERROR',
      op.method === 'POST' && op.kind !== 'login' && response.status >= 500,
    );
  }
  try {
    return schemas[op.kind](value);
  } catch {
    throw new ApiError(
      502,
      'INVALID_BACKEND_RESPONSE',
      op.method === 'POST' && op.kind !== 'login',
    );
  }
}
