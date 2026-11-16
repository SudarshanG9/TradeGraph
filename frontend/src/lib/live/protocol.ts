export const eventTypes = [
  'book.changed',
  'trade.committed',
  'order.changed',
  'account.changed',
  'simulator.changed',
  'service.degraded',
  'resync.required',
] as const;
export interface LiveEvent {
  schema_version: 1;
  type: (typeof eventTypes)[number];
  epoch: string;
  sequence: number;
  published_at: string;
  instrument_id?: number;
  version?: number;
  execution_id?: string;
}
export function decodeEvent(value: unknown): LiveEvent {
  if (!value || typeof value !== 'object') throw new Error('INVALID_LIVE_EVENT');
  const v = value as Record<string, unknown>;
  if (
    Object.keys(v).some(
      (k) =>
        ![
          'schema_version',
          'type',
          'epoch',
          'sequence',
          'published_at',
          'instrument_id',
          'version',
          'execution_id',
        ].includes(k),
    ) ||
    v.schema_version !== 1 ||
    !eventTypes.includes(v.type as LiveEvent['type']) ||
    typeof v.epoch !== 'string' ||
    !v.epoch ||
    v.epoch.length > 128 ||
    !Number.isSafeInteger(v.sequence) ||
    (v.sequence as number) < 1 ||
    typeof v.published_at !== 'string' ||
    !Number.isFinite(Date.parse(v.published_at))
  )
    throw new Error('INVALID_LIVE_EVENT');
  if (
    v.instrument_id !== undefined &&
    (!Number.isSafeInteger(v.instrument_id) || (v.instrument_id as number) < 1)
  )
    throw new Error('INVALID_LIVE_EVENT');
  if (v.version !== undefined && (!Number.isSafeInteger(v.version) || (v.version as number) < 0))
    throw new Error('INVALID_LIVE_EVENT');
  if (
    v.execution_id !== undefined &&
    (typeof v.execution_id !== 'string' || !/^[1-9][0-9]*$/.test(v.execution_id))
  )
    throw new Error('INVALID_LIVE_EVENT');
  if (v.type === 'book.changed' && (v.instrument_id === undefined || v.version === undefined))
    throw new Error('INVALID_LIVE_EVENT');
  if (
    v.type === 'trade.committed' &&
    (v.instrument_id === undefined || v.execution_id === undefined)
  )
    throw new Error('INVALID_LIVE_EVENT');
  return v as unknown as LiveEvent;
}
