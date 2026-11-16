import { createSubmissionTracker, createCancellationTracker } from './submission';
import { ApiError } from './errors';
import { schemas, type ApiResult, type ResponseKind } from './schema';
import type { Services, PageQuery } from '../services';

export async function apiRequest<K extends ResponseKind>(
  kind: K,
  path: string,
  body?: unknown,
  key?: string,
  signal?: AbortSignal,
): Promise<ApiResult<K>> {
  const timeout = AbortSignal.timeout(kind === 'optimizer' ? 40000 : 18000);
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;
  let response: Response;
  try {
    response = await fetch(`/api/backend/${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      signal: combined,
      headers: {
        'Content-Type': 'application/json',
        'X-TradeGraph-Request': '1',
        ...(key ? { 'Idempotency-Key': key } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    if (signal?.aborted) throw signal.reason;
    throw new ApiError(
      timeout.aborted ? 504 : 503,
      timeout.aborted ? 'REQUEST_TIMEOUT' : 'CONNECTION_UNAVAILABLE',
      body !== undefined && kind !== 'login',
    );
  }
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    if (signal?.aborted) throw signal.reason;
    throw new ApiError(
      timeout.aborted ? 504 : 502,
      timeout.aborted ? 'REQUEST_TIMEOUT' : 'INVALID_RESPONSE',
      body !== undefined,
    );
  }
  if (signal?.aborted) throw signal.reason;
  if (!response.ok) {
    if (response.status === 401 && typeof window !== 'undefined')
      window.dispatchEvent(new Event('tradegraph:expired'));
    const e = value && typeof value === 'object' && 'error' in value ? value.error : null;
    const code =
      e && typeof e === 'object' && 'code' in e && typeof e.code === 'string'
        ? e.code
        : 'REQUEST_FAILED';
    const uncertain = !!(e && typeof e === 'object' && 'uncertain' in e && e.uncertain === true);
    throw new ApiError(response.status, code, uncertain);
  }
  try {
    return schemas[kind](value) as ApiResult<K>;
  } catch {
    throw new ApiError(502, 'INVALID_RESPONSE', body !== undefined);
  }
}
const query = (values: Record<string, string | number | undefined>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(values)) if (v !== undefined) p.set(k, String(v));
  return p.toString();
};
const page = (q: PageQuery = {}) => query({ limit: q.limit, before_id: q.before_id });
const market = (symbol: string, suffix: string) => `market/${encodeURIComponent(symbol)}/${suffix}`;
export function createRealDataServices(): Omit<Services, 'auth'> {
  // Resolve storage lazily: this service is also constructed during SSR.
  const tracker = () => {
    if (typeof window === 'undefined') throw new ApiError(503, 'BROWSER_REQUIRED');
    return createSubmissionTracker(window.sessionStorage);
  };
  const scope = async () => (await apiRequest('account', 'account/me')).trader_id;
  const dispatch = (key: string, order: import('../contracts').NewOrder) =>
    apiRequest('submit', 'orders', order, key);
  return {
    instruments: { list: () => apiRequest('instruments', 'instruments') },
    account: { get: (signal) => apiRequest('account', 'account/me', undefined, undefined, signal) },
    orders: {
      list: (q, signal) =>
        apiRequest('orders', `orders/me?${page(q)}`, undefined, undefined, signal),
      submit: async (order) => tracker().beginSubmission(await scope(), order, dispatch),
      pending: async () => !!tracker().getPendingSubmission(await scope()),
      reconcile: async () =>
        tracker().reconcileSubmission(await scope(), (key) =>
          apiRequest('requestOutcome', `orders/requests/${key}`),
        ),
      retry: async () => tracker().retrySubmission(await scope(), dispatch),
      cancel: async (id) =>
        createCancellationTracker(window.sessionStorage).cancel(await scope(), id, () =>
          apiRequest('cancel', `orders/${id}/cancel`, null),
        ),
      cancelPending: (scope, id) =>
        createCancellationTracker(window.sessionStorage).pending(scope, id),
      reconcileCancel: (scope, id) =>
        createCancellationTracker(window.sessionStorage).reconcile(scope, id, () =>
          apiRequest('order', `orders/${id}`),
        ),
    },
    market: {
      book: (symbol, signal) =>
        apiRequest('book', market(symbol, 'book'), undefined, undefined, signal),
      trades: (symbol, q, signal) =>
        apiRequest(
          'trades',
          `${market(symbol, 'trades')}?${page(q)}`,
          undefined,
          undefined,
          signal,
        ),
      analytics: (symbol, lower, upper, signal) =>
        apiRequest(
          'analytics',
          `${market(symbol, 'analytics')}?${query({ lower_ticks: lower, upper_ticks: upper })}`,
          undefined,
          undefined,
          signal,
        ),
    },
    health: { get: (signal) => apiRequest('health', 'health', undefined, undefined, signal) },
    surveillance: {
      cycles: (limit) => apiRequest('cycles', `admin/surveillance/cycles?${query({ limit })}`),
    },
    regimes: {
      similar: (q) => {
        const p = new URLSearchParams(query({ instrument_id: q.instrument_id, k: q.k }));
        if (q.current) p.set('current', 'true');
        else q.features.forEach((x) => p.append('features', String(x)));
        return apiRequest('similar', `admin/regimes/similar?${p}`);
      },
    },
    disclosures: {
      search: (q, limit = 20) =>
        apiRequest('search', `admin/disclosures/search?${query({ q, limit })}`),
    },
    optimizer: {
      compare: (scenario, instrument_id, lower_ticks, upper_ticks) =>
        apiRequest(
          'optimizer',
          `admin/optimizer/compare?${query({ scenario, ...(scenario === 'price_band' ? { instrument_id, lower_ticks, upper_ticks } : {}) })}`,
        ),
    },
    desks: { rollup: () => apiRequest('desks', 'admin/desks/rollup') },
    simulator: {
      status: (signal) =>
        apiRequest('simulator', 'admin/simulator/status', undefined, undefined, signal),
      start: (config) => apiRequest('simulator', 'admin/simulator/start', config),
      stop: () => apiRequest('simulator', 'admin/simulator/stop', null),
      recover: () => apiRequest('simulator', 'admin/simulator/recover', null),
    },
  };
}
