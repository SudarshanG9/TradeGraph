import type { Trade } from './contracts';
/** Retain bounded observed history, deduplicate exact IDs, never fabricate missing trades. */
export function mergeExecutions(
  previous: Trade[],
  incoming: Trade[],
  instrument: number,
  limit = 1000,
): Trade[] {
  return [
    ...new Map(
      [...previous, ...incoming]
        .filter((t) => t.instrument_id === instrument)
        .map((t) => [t.id, t]),
    ).values(),
  ]
    .sort((a, b) => (BigInt(a.id) > BigInt(b.id) ? -1 : BigInt(a.id) < BigInt(b.id) ? 1 : 0))
    .slice(0, limit);
}
