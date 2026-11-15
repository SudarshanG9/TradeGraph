'use client';
import type { OrderSummary } from '@/lib/contracts';
import { fmt, time } from '@/lib/exact';
import { Card, Empty, OrderStatus, Table } from '../ui';
import { useSymbolFor } from './positions-table';
export function RecentOrders({ orders }: { orders: OrderSummary[] }) {
  const symbolFor = useSymbolFor();
  return (
    <Card title="Recent Orders">
      <Table
        label="Recent Orders"
        headers={[
          'Order',
          'Instr.',
          'Side',
          'Price (ticks)',
          'Qty',
          'Filled',
          'Status',
          'Submitted (UTC)',
        ]}
      >
        {orders.map((o) => (
          <tr key={o.id}>
            <td className="mono">#{o.id}</td>
            <td>{symbolFor(o.instrument_id)}</td>
            <td>
              <OrderStatus status={o.side} />
            </td>
            <td className="mono">{fmt(o.price_ticks)}</td>
            <td className="mono">{fmt(o.quantity)}</td>
            <td className="mono">{fmt(o.filled_quantity)}</td>
            <td>
              <OrderStatus status={o.status} />
            </td>
            <td className="muted" title={o.created_at}>
              {time(o.created_at, true)}
            </td>
          </tr>
        ))}
      </Table>
      {!orders.length && <Empty message="No demo orders yet." />}
    </Card>
  );
}
