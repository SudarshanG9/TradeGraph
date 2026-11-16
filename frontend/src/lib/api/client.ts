import { createSubmissionGate } from './submission';
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
  let response: Response;
  try {
    response = await fetch(`/api/backend/${path}`, {
      method: body === undefined ? 'GET' : 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      signal,
      headers: {
        'Content-Type': 'application/json',
        'X-TradeGraph-Request': '1',
        ...(key ? { 'Idempotency-Key': key } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(502, 'CONNECTION_UNAVAILABLE', body !== undefined && kind !== 'login');
  }
  let value: unknown;
  try {
    value = await response.json();
  } catch {
    throw new ApiError(502, 'INVALID_RESPONSE', body !== undefined);
  }
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
  return schemas[kind](value) as ApiResult<K>;
}
const query = (values: Record<string, string | number | undefined>) => {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(values)) if (v !== undefined) p.set(k, String(v));
  return p.toString();
};
const page = (q: PageQuery = {}) => query({ limit: q.limit, before_id: q.before_id });
const market = (symbol: string, suffix: string) => `market/${encodeURIComponent(symbol)}/${suffix}`;
export function createRealDataServices(): Omit<Services, 'auth'> {
  const submit = createSubmissionGate(
    typeof window === 'undefined' ? undefined : window.sessionStorage,
  );
  return {
    instruments: { list: () => apiRequest('instruments', 'instruments') },
    account: { get: (signal) => apiRequest('account', 'account/me', undefined, undefined, signal) },
    orders: {
      list: (q) => apiRequest('orders', `orders/me?${page(q)}`),
      submit: (order) => submit((key) => apiRequest('submit', 'orders', order, key)),
      cancel: (id) => apiRequest('cancel', `orders/${id}/cancel`, null),
    },
    market: {
      book: (symbol) => apiRequest('book', market(symbol, 'book')),
      trades: (symbol, q) => apiRequest('trades', `${market(symbol, 'trades')}?${page(q)}`),
      analytics: (symbol, lower, upper) =>
        apiRequest(
          'analytics',
          `${market(symbol, 'analytics')}?${query({ lower_ticks: lower, upper_ticks: upper })}`,
        ),
    },
    health: { get: () => apiRequest('health', 'health') },
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
      status: () => apiRequest('simulator', 'admin/simulator/status'),
      start: (config) => apiRequest('simulator', 'admin/simulator/start', config),
      stop: () => apiRequest('simulator', 'admin/simulator/stop', null),
    },
  };
}
