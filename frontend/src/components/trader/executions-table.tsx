'use client';
import type { Trade } from '@/lib/contracts';
import { fmt, time } from '@/lib/exact';
import { Card, Empty, Table } from '../ui';
import { symbolFor } from './positions-table';
import type { ReactNode } from 'react';
export function ExecutionsTable({
  trades,
  mode = 'dashboard',
  action,
  children,
}: {
  trades: Trade[];
  mode?: 'dashboard' | 'terminal' | 'analytics';
  action?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <Card title="Recent Executions" action={action}>
      <Table
        label="Recent Executions"
        headers={
          mode === 'dashboard'
            ? ['Execution', 'Instrument', 'Price (ticks)', 'Qty', 'Time (UTC)']
            : mode === 'analytics'
              ? ['Execution', 'Price (ticks)', 'Qty', 'Buy Order', 'Sell Order', 'Time (UTC)']
              : ['Execution', 'Price (ticks)', 'Qty', 'Time (UTC)']
        }
      >
        {trades.map((t) => (
          <tr key={t.id}>
            <td className="mono">EX-{t.id}</td>
            {mode === 'dashboard' && <td>{symbolFor(t.instrument_id)}</td>}
            <td className="mono">{fmt(t.price_ticks)}</td>
            <td className="mono">{fmt(t.quantity)}</td>
            {mode === 'analytics' && (
              <>
                <td className="mono">#{t.buy_order_id}</td>
                <td className="mono">#{t.sell_order_id}</td>
              </>
            )}
            <td className="muted" title={t.executed_at}>
              {time(t.executed_at, mode === 'analytics')}
            </td>
          </tr>
        ))}
      </Table>
      {!trades.length && (
        <Empty message="No settled execution observations in this demo fixture." />
      )}
      {children}
    </Card>
  );
}
