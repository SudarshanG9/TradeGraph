import { isLosslessNumber } from 'lossless-json';
import { boundedNumber, MAX_INT, MAX_PRICE, normalizeInteger } from '../exact';
import type * as C from '../contracts';

export type Decoder<T> = (value: unknown) => T;
const bad = (): never => {
  throw new Error('INVALID_RESPONSE');
};
export const str: Decoder<string> = (v) => (typeof v === 'string' ? v : bad());
export const bool: Decoder<boolean> = (v) => (typeof v === 'boolean' ? v : bad());
export const oneOf =
  <T extends string>(...values: T[]): Decoder<T> =>
  (v) =>
    typeof v === 'string' && values.includes(v as T) ? (v as T) : bad();
export const nullable =
  <T>(read: Decoder<T>): Decoder<T | null> =>
  (v) =>
    v === null ? null : read(v);
export const array =
  <T>(read: Decoder<T>): Decoder<T[]> =>
  (v) =>
    Array.isArray(v) ? v.map(read) : bad();
export function object<S extends Record<string, Decoder<unknown>>>(
  shape: S,
): Decoder<{ [K in keyof S]: ReturnType<S[K]> }> {
  return (v) => {
    if (!v || typeof v !== 'object' || Array.isArray(v)) return bad();
    const record = v as Record<string, unknown>;
    return Object.fromEntries(Object.entries(shape).map(([k, read]) => [k, read(record[k])])) as {
      [K in keyof S]: ReturnType<S[K]>;
    };
  };
}
export const exact =
  (min = 0n, max = MAX_INT): Decoder<C.Int> =>
  (v) => {
    const n = normalizeInteger(v);
    return BigInt(n) >= min && BigInt(n) <= max ? n : bad();
  };
export const count =
  (min: number, max: number): Decoder<number> =>
  (v) =>
    boundedNumber(v, min, max);
export const finite: Decoder<number> = (v) => {
  if (typeof v !== 'number' && typeof v !== 'bigint' && !isLosslessNumber(v)) return bad();
  const n = Number(String(v));
  return Number.isFinite(n) ? n : bad();
};
export const timestamp: Decoder<string> = (v) => {
  const s = str(v);
  return /^\d{4}-\d\d-\d\dT.*(?:Z|[+-]\d\d:\d\d)$/.test(s) && Number.isFinite(Date.parse(s))
    ? s
    : bad();
};
export const uuid: Decoder<string> = (v) => {
  const s = str(v);
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s) ? s : bad();
};
const record =
  <T>(read: Decoder<T>): Decoder<Record<string, T>> =>
  (v) => {
    if (!v || typeof v !== 'object' || Array.isArray(v)) return bad();
    return Object.fromEntries(Object.entries(v).map(([k, val]) => [k, read(val)]));
  };
export const role = oneOf('TRADER', 'COMPLIANCE_ADMIN');
const id = count(1, 2147483647),
  positive = exact(1n),
  signed = exact(-MAX_INT - 1n);
const price = exact(1n, MAX_PRICE),
  stamp = nullable(timestamp),
  cursor = nullable(positive);
const features: Decoder<C.Features> = (v) => {
  const a = array(finite)(v);
  return a.length === 6 ? [a[0], a[1], a[2], a[3], a[4], a[5]] : bad();
};
export const simulationConfig: Decoder<C.SimulationStart> = object({
  instrument_ids: (v) => {
    const a = array(id)(v);
    return a.length >= 1 && a.length <= 3 && new Set(a).size === a.length ? a : bad();
  },
  bot_count: count(4, 8),
  orders_per_second: count(1, 5),
  volatility: oneOf('low', 'medium', 'high'),
  seed: exact(),
  max_duration_seconds: count(30, 600),
});
const plan: Decoder<C.PlanNode> = (v) => {
  const base = object({ 'Node Type': str })(v);
  const r = v as Record<string, unknown>;
  const out: C.PlanNode = { ...base };
  for (const k of ['Relation Name', 'Index Name', 'Filter', 'Index Cond', 'Recheck Cond'] as const)
    if (r[k] !== undefined) out[k] = str(r[k]);
  for (const k of ['Startup Cost', 'Total Cost'] as const)
    if (r[k] !== undefined) out[k] = finite(r[k]);
  for (const k of ['Actual Rows', 'Shared Hit Blocks', 'Shared Read Blocks'] as const)
    if (r[k] !== undefined) out[k] = exact()(r[k]);
  if (r.Plans !== undefined) out.Plans = array(plan)(r.Plans);
  return out;
};
const explain: Decoder<C.ExplainPlan> = (v) => {
  const out: C.ExplainPlan = object({ Plan: plan })(v);
  const r = v as Record<string, unknown>;
  for (const k of ['Execution Time', 'Planning Time'] as const)
    if (r[k] !== undefined) out[k] = finite(r[k]);
  return out;
};
export const schemas = {
  login: object({
    access_token: str,
    token_type: oneOf('bearer'),
    role,
    expires_in: count(60, 3600),
  }),
  instruments: object({
    items: array(
      object({ id, symbol: str, tick_size: positive, lot_size: positive, is_active: bool }),
    ),
  }),
  account: object({
    trader_id: uuid,
    cash_balance: exact(),
    escrow_balance: exact(),
    positions: array(
      object({
        instrument_id: id,
        net_quantity: signed,
        realized_pnl: signed,
        pnl_basis: oneOf('gross'),
      }),
    ),
  }),
  order: object({
    id: positive,
    trader_id: uuid,
    instrument_id: id,
    side: oneOf('BUY', 'SELL'),
    price_ticks: price,
    quantity: positive,
    filled_quantity: exact(),
    status: oneOf('OPEN', 'PARTIAL', 'FILLED', 'CANCELLED'),
    created_at: timestamp,
    updated_at: timestamp,
    archived: bool,
  }),
  orders: object({
    items: array(
      object({
        id: positive,
        trader_id: uuid,
        instrument_id: id,
        side: oneOf('BUY', 'SELL'),
        price_ticks: price,
        quantity: positive,
        filled_quantity: exact(),
        status: oneOf('OPEN', 'PARTIAL', 'FILLED', 'CANCELLED'),
        created_at: timestamp,
        updated_at: timestamp,
        archived: bool,
      }),
    ),
    next_before_id: cursor,
  }),
  submit: object({ order_id: positive, status: oneOf('OPEN'), accepted_at: timestamp }),
  requestOutcome: object({
    trader_id: uuid,
    status: oneOf('ACCEPTED', 'UNRESOLVED'),
    accepted_order: nullable(
      object({ order_id: positive, status: oneOf('OPEN'), accepted_at: timestamp }),
    ),
  }),
  cancel: object({ order_id: positive, status: oneOf('CANCELLED'), cancelled_quantity: exact() }),
  book: object({
    symbol: str,
    bids: array(object({ price_ticks: price, quantity: positive })),
    asks: array(object({ price_ticks: price, quantity: positive })),
    as_of: stamp,
    stale: bool,
    version: exact(),
  }),
  trades: object({
    items: array(
      object({
        id: positive,
        instrument_id: id,
        buy_order_id: positive,
        sell_order_id: positive,
        buy_trader_id: uuid,
        sell_trader_id: uuid,
        price_ticks: price,
        quantity: positive,
        executed_at: timestamp,
      }),
    ),
    next_before_id: cursor,
  }),
  analytics: object({
    vwap_ticks: nullable((v) => {
      const s = str(v);
      return /^\d+(?:\.\d+)?$/.test(s) ? s : bad();
    }),
    window_fills: count(0, 100),
    band_volume: exact(),
    as_of: stamp,
  }),
  health: object({
    status: oneOf('ok', 'unhealthy'),
    dependencies: record(oneOf('up', 'down')),
    trading_ready: bool,
  }),
  cycles: object({
    candidates: array(object({ trader_ids: array(uuid), edge_counts: array(exact()) })),
  }),
  similar: object({
    matches: array(
      object({
        id: positive,
        instrument_id: id,
        captured_at: timestamp,
        features,
        cosine_distance: finite,
      }),
    ),
  }),
  search: object({
    items: array(
      object({
        id: positive,
        instrument_id: nullable(id),
        title: str,
        published_at: timestamp,
        rank: finite,
      }),
    ),
  }),
  optimizer: object({
    scenario: oneOf('price_band', 'recent_executions'),
    row_count: exact(),
    dataset_size: exact(),
    plans: object({ forced_sequential: explain, automatic: explain }),
  }),
  desks: object({
    items: array(object({ desk_id: id, realized_pnl: signed, execution_volume: exact() })),
  }),
  simulator: object({
    run_id: nullable(uuid),
    state: oneOf('RUNNING', 'STOPPING', 'STOPPED', 'ERROR'),
    started_at: stamp,
    stopped_at: stamp,
    active_bots: count(0, 8),
    instrument_ids: array(id),
    config: nullable(simulationConfig),
    orders_attempted: exact(),
    orders_accepted: exact(),
    orders_rejected: exact(),
    orders_cancelled: exact(),
    backpressure_events: exact(),
    active_bot_orders: exact(),
    committed_executions: exact(),
    last_action_at: stamp,
    last_error: nullable(str),
    derived_workers: record(oneOf('ready', 'retrying', 'initializing')),
  }),
} satisfies Record<string, Decoder<unknown>>;
export type ResponseKind = keyof typeof schemas;
export type ApiResult<K extends ResponseKind> = ReturnType<(typeof schemas)[K]>;
