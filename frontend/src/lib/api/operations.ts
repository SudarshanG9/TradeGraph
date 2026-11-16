import type { AccountRole } from '../contracts';
import { integer, MAX_PRICE, parseWire, serializeOrder, serializeSimulationStart } from '../exact';
import { ApiError } from './errors';
import { count, object, oneOf, simulationConfig, str, type ResponseKind } from './schema';

export interface Operation {
  path: string;
  method: 'GET' | 'POST';
  kind: ResponseKind;
  role?: AccountRole;
  authenticated: boolean;
  csrf: boolean;
  body?: string;
  idempotencyKey?: string;
}
const invalid = (): never => {
  throw new ApiError(422, 'INVALID_REQUEST');
};
const exactKeys = (v: unknown, keys: string[]) => {
  if (
    !v ||
    typeof v !== 'object' ||
    Array.isArray(v) ||
    Object.keys(v).some((k) => !keys.includes(k))
  )
    invalid();
};
/** This is the only backend route allowlist. No caller supplies a destination URL. */
export function operation(
  method: string,
  segments: string[],
  query: URLSearchParams,
  raw?: string,
  key?: string,
): Operation {
  try {
    const name = segments.join('/');
    let path = `/${name}`,
      kind: ResponseKind,
      requiredRole: AccountRole | undefined;
    let allowed: string[] = [],
      csrf = method !== 'GET',
      body: string | undefined;
    if (method === 'POST' && name === 'login') {
      const v = parseWire(raw ?? '');
      exactKeys(v, ['email', 'password']);
      const login = object({ email: str, password: str })(v);
      if (
        login.email.length < 3 ||
        login.email.length > 255 ||
        !login.password.length ||
        login.password.length > 72
      )
        invalid();
      body = JSON.stringify(login);
      kind = 'login';
    } else if (method === 'GET' && name === 'instruments') kind = 'instruments';
    else if (method === 'GET' && name === 'account/me') {
      kind = 'account';
      requiredRole = 'TRADER';
    } else if (method === 'GET' && name === 'orders/me') {
      kind = 'orders';
      requiredRole = 'TRADER';
      allowed = ['limit', 'before_id'];
    } else if (
      method === 'GET' &&
      segments.length === 3 &&
      segments[0] === 'orders' &&
      segments[1] === 'requests'
    ) {
      if (['.', '..'].includes(segments[2]) || !/^[A-Za-z0-9._-]{1,128}$/.test(segments[2]))
        invalid();
      kind = 'requestOutcome';
      requiredRole = 'TRADER';
    } else if (method === 'GET' && segments.length === 2 && segments[0] === 'orders') {
      integer(segments[1]);
      kind = 'order';
      requiredRole = 'TRADER';
    } else if (method === 'POST' && name === 'orders') {
      const v = parseWire(raw ?? '');
      exactKeys(v, ['instrument_id', 'side', 'price_ticks', 'quantity']);
      const order = object({
        instrument_id: count(1, 2147483647),
        side: oneOf('BUY', 'SELL'),
        price_ticks: (v) => integer(str(v), 1n, MAX_PRICE).toString() as `${bigint}`,
        quantity: (v) => integer(str(v)).toString() as `${bigint}`,
      })(v);
      if (!key || !/^[A-Za-z0-9._-]{1,128}$/.test(key)) invalid();
      body = serializeOrder(order);
      kind = 'submit';
      requiredRole = 'TRADER';
    } else if (
      method === 'POST' &&
      segments.length === 3 &&
      segments[0] === 'orders' &&
      segments[2] === 'cancel'
    ) {
      integer(segments[1]);
      kind = 'cancel';
      requiredRole = 'TRADER';
    } else if (
      method === 'GET' &&
      segments.length === 3 &&
      segments[0] === 'market' &&
      ['book', 'trades', 'analytics'].includes(segments[2])
    ) {
      if (
        !segments[1] ||
        segments[1].length > 128 ||
        /[\x00-\x1f/\\?#]/.test(segments[1]) ||
        ['.', '..'].includes(segments[1])
      )
        invalid();
      path = `/market/${encodeURIComponent(segments[1])}/${segments[2]}`;
      kind = segments[2] as 'book' | 'trades' | 'analytics';
      allowed =
        kind === 'trades'
          ? ['limit', 'before_id']
          : kind === 'analytics'
            ? ['lower_ticks', 'upper_ticks']
            : [];
    } else if (method === 'GET' && name === 'health') {
      kind = 'health';
      requiredRole = 'COMPLIANCE_ADMIN';
    } else if (method === 'GET' && name === 'admin/surveillance/cycles') {
      kind = 'cycles';
      allowed = ['limit'];
    } else if (method === 'GET' && name === 'admin/regimes/similar') {
      kind = 'similar';
      allowed = ['instrument_id', 'k', 'current', 'features'];
      csrf = true;
    } else if (method === 'GET' && name === 'admin/disclosures/search') {
      kind = 'search';
      allowed = ['q', 'limit'];
    } else if (method === 'GET' && name === 'admin/optimizer/compare') {
      kind = 'optimizer';
      allowed = ['scenario', 'instrument_id', 'lower_ticks', 'upper_ticks'];
      csrf = true;
    } else if (method === 'GET' && name === 'admin/desks/rollup') kind = 'desks';
    else if (name === 'admin/simulator/status' && method === 'GET') kind = 'simulator';
    else if (name === 'admin/simulator/stop' && method === 'POST') kind = 'simulator';
    else if (name === 'admin/simulator/start' && method === 'POST') {
      const v = parseWire(raw ?? '');
      exactKeys(v, [
        'instrument_ids',
        'bot_count',
        'orders_per_second',
        'volatility',
        'seed',
        'max_duration_seconds',
      ]);
      body = serializeSimulationStart(simulationConfig(v));
      kind = 'simulator';
    } else throw new ApiError(404, 'NOT_FOUND');
    if (name.startsWith('admin/')) requiredRole = 'COMPLIANCE_ADMIN';
    if (!body && raw && raw.trim() && raw.trim() !== 'null') invalid();
    for (const k of query.keys()) {
      if (!allowed.includes(k) || (k !== 'features' && query.getAll(k).length !== 1)) invalid();
    }
    for (const k of ['limit', 'k']) if (query.has(k)) integer(query.get(k)!, 1n, 100n);
    if (query.has('before_id')) integer(query.get('before_id')!);
    if (query.has('instrument_id')) integer(query.get('instrument_id')!, 1n, 2147483647n);
    for (const k of ['lower_ticks', 'upper_ticks'])
      if (query.has(k)) integer(query.get(k)!, kind === 'optimizer' ? 1n : 0n, MAX_PRICE);
    if (
      query.has('lower_ticks') &&
      query.has('upper_ticks') &&
      BigInt(query.get('lower_ticks')!) > BigInt(query.get('upper_ticks')!)
    )
      invalid();
    if (kind === 'search' && (!query.get('q')?.trim() || query.get('q')!.length > 500)) invalid();
    if (
      kind === 'optimizer' &&
      query.has('scenario') &&
      !['price_band', 'recent_executions'].includes(query.get('scenario')!)
    )
      invalid();
    if (kind === 'similar') {
      if (!query.has('instrument_id')) invalid();
      const f = query.getAll('features');
      if (query.has('current')) {
        if (query.get('current') !== 'true' || f.length) invalid();
      } else if (
        f.length !== 6 ||
        f.some((x) => !x.trim() || !Number.isFinite(Number(x))) ||
        !f.some((x) => Number(x) !== 0)
      )
        invalid();
    }
    if (query.size) path += `?${query}`;
    return {
      path,
      method: method as 'GET' | 'POST',
      kind,
      role: requiredRole,
      authenticated: kind !== 'login',
      csrf,
      body,
      idempotencyKey: kind === 'submit' ? key : undefined,
    };
  } catch (e) {
    if (e instanceof ApiError) throw e;
    return invalid();
  }
}
