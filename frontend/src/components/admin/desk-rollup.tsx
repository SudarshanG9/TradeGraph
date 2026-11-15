'use client';
import { useState } from 'react';
import type { Desk } from '@/lib/contracts';
import { fmt } from '@/lib/exact';
import { Card, Empty, Table } from '../ui';
export function DeskRollup({ desks }: { desks: Desk[] }) {
  const [sort, setSort] = useState<keyof Desk>('desk_id'),
    [ascending, setAscending] = useState(true);
  const sorted = [...desks].sort((a, b) => {
    const x = BigInt(a[sort]),
      y = BigInt(b[sort]);
    return (x < y ? -1 : x > y ? 1 : 0) * (ascending ? 1 : -1);
  });
  return (
    <Card>
      <div className="toolbar desk-sort">
        <span className="caption">Sort by</span>
        {[
          ['desk_id', 'Desk ID'],
          ['realized_pnl', 'Gross realized PnL'],
          ['execution_volume', 'Execution volume'],
        ].map(([key, label]) => (
          <button
            className="link"
            key={key}
            aria-pressed={sort === key}
            onClick={() => {
              if (sort === key) setAscending((v) => !v);
              else {
                setSort(key as keyof Desk);
                setAscending(true);
              }
            }}
          >
            {label}
            {sort === key ? (ascending ? ' ↑' : ' ↓') : ''}
          </button>
        ))}
      </div>
      <Table
        label="Desk aggregates"
        headers={['Desk ID', 'Gross Realized PnL (minor units)', 'Execution Volume (units)']}
      >
        {sorted.map((d) => (
          <tr key={d.desk_id}>
            <td className="mono">D-{String(d.desk_id).padStart(2, '0')}</td>
            <td className={`mono ${BigInt(d.realized_pnl) >= 0n ? 'positive' : 'negative'}`}>
              {fmt(d.realized_pnl, true)}
            </td>
            <td className="mono">{fmt(d.execution_volume)}</td>
          </tr>
        ))}
      </Table>
      {!desks.length && <Empty message="No desk rollups in this demo fixture." />}
    </Card>
  );
}
