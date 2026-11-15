import { parse, stringify } from 'lossless-json';
import type { Int, InstrumentInfo, NewOrder, SimulationStart } from './contracts';

export const MAX_INT = 9223372036854775807n;
export const MAX_PRICE = 9007199254740991n;
/** All integer tokens become bigint; fractional JSON numbers remain LosslessNumber.
 * A future adapter must explicitly normalize each response, never cast this to a model. */
export function parseWire(text: string): unknown {
  return parse(text, undefined, (value) => (/^-?\d+$/.test(value) ? BigInt(value) : parse(value)));
}
export function normalizeInteger(value: unknown): Int {
  if (typeof value === 'bigint') return value.toString() as Int;
  if (typeof value === 'number' && Number.isSafeInteger(value)) return String(value) as Int;
  if (typeof value === 'string' && /^-?\d+$/.test(value)) return BigInt(value).toString() as Int;
  throw new Error('Expected a lossless integer');
}
export function boundedNumber(value: unknown, min: number, max: number): number {
  const n = BigInt(normalizeInteger(value));
  if (n < BigInt(min) || n > BigInt(max)) throw new Error('Integer outside supported bounds');
  return Number(n);
}
export function integer(text: string, min = 1n, max = MAX_INT): bigint {
  if (!/^\d+$/.test(text)) throw new Error('Enter a whole number.');
  const n = BigInt(text);
  if (n < min || n > max) throw new Error(`Enter a value from ${min} to ${max}.`);
  return n;
}
export function validateOrder(order: NewOrder, instrument: InstrumentInfo): bigint {
  if (!instrument.is_active || order.instrument_id !== instrument.id)
    throw new Error('Select an active instrument.');
  const p = integer(order.price_ticks, 1n, MAX_PRICE),
    q = integer(order.quantity);
  if (q % BigInt(instrument.lot_size))
    throw new Error(`Quantity must be a multiple of ${instrument.lot_size}.`);
  const total = p * q * BigInt(instrument.tick_size);
  if (total > MAX_INT) throw new Error('Estimated notional exceeds the supported BIGINT range.');
  return total;
}
/** Serialize exact outgoing values as numeric JSON tokens, not quoted numbers. */
export function serializeOrder(order: NewOrder): string {
  return stringify({
    ...order,
    price_ticks: BigInt(order.price_ticks),
    quantity: BigInt(order.quantity),
  })!;
}
export function fmt(value: string | bigint, signed = false): string {
  const n = BigInt(value),
    text = (n < 0n ? -n : n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
  return `${n < 0n ? '−' : signed && n > 0n ? '+' : ''}${text}`;
}
export function decimal(value: string | null): string {
  return value === null ? '—' : value;
}
export function time(value: string | null, full = false): string {
  if (!value) return 'No observation';
  const date = new Date(value);
  return new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC',
    ...(full ? ({ month: 'short', day: '2-digit' } as const) : {}),
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);
}
export const date = (value: string) =>
  new Intl.DateTimeFormat('en-GB', {
    timeZone: 'UTC',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  }).format(new Date(value));
export const homeFor = (role: import('./contracts').AccountRole) =>
  role === 'TRADER' ? '/trader/dashboard' : '/admin/overview';
export function assertRole(
  session: import('./contracts').PreviewSession | null,
  role: import('./contracts').AccountRole,
): void {
  if (!session || session.kind !== 'mock-preview' || session.expiresAt <= Date.now())
    throw new Error('SESSION_EXPIRED');
  if (session.role !== role) throw new Error('ROLE_MISMATCH');
}

export function serializeSimulationStart(config: SimulationStart): string {
  return stringify({ ...config, seed: integer(config.seed, 0n) })!;
}
