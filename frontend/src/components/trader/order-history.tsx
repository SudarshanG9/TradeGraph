'use client';
import type { OrderSummary } from '@/lib/contracts';
import { fmt, time } from '@/lib/exact';
import { Card, Empty, OrderStatus, Table } from '../ui';
import { useSymbolFor } from './positions-table';
export function OrderHistory({
  orders,
  selected,
  onSelect,
  onCancel,
  children,
}: {
  orders: OrderSummary[];
  selected: string | null;
  onSelect: (o: OrderSummary) => void;
  onCancel: (o: OrderSummary) => void;
  children: React.ReactNode;
}) {
  const symbolFor = useSymbolFor();
  return (
    <Card className="history-card">
      <Table
        label="Order history"
        headers={[
          'Order',
          'Instr.',
          'Side',
          'Price',
          'Orig. Qty',
          'Filled',
          'Unfilled',
          'Status',
          'Submitted (UTC)',
          'Action',
        ]}
      >
        {orders.map((o) => (
          <tr key={o.id} className={selected === o.id ? 'selected' : ''}>
            <td>
              <button
                className="link mono"
                aria-label={`View order ${o.id}`}
                onClick={() => onSelect(o)}
              >
                #{o.id}
              </button>
            </td>
            <td>{symbolFor(o.instrument_id)}</td>
            <td>
              <OrderStatus status={o.side} />
            </td>
            <td className="mono">{fmt(o.price_ticks)}</td>
            <td className="mono">{fmt(o.quantity)}</td>
            <td className="mono">{fmt(o.filled_quantity)}</td>
            <td className="mono">{fmt(BigInt(o.quantity) - BigInt(o.filled_quantity))}</td>
            <td>
              <OrderStatus status={o.status} />
              {o.archived && <span className="caption"> · Archived</span>}
            </td>
            <td className="muted" title={o.created_at}>
              {time(o.created_at, true)}
            </td>
            <td>
              {['OPEN', 'PARTIAL'].includes(o.status) ? (
                <button className="link negative" onClick={() => onCancel(o)}>
                  Cancel
                </button>
              ) : (
                <span className="caption">{o.archived ? 'Archived' : '—'}</span>
              )}
            </td>
          </tr>
        ))}
      </Table>
      {!orders.length && <Empty message="No orders match this filter in the loaded cursor page." />}
      {children}
    </Card>
  );
}
export function OrderDetails({
  order,
  onCancel,
}: {
  order: OrderSummary | null;
  onCancel: (o: OrderSummary) => void;
}) {
  const symbolFor = useSymbolFor();
  if (!order)
    return (
      <Card title="Order Details">
        <Empty message="Select an order to inspect its contract fields." />
      </Card>
    );
  const remaining = BigInt(order.quantity) - BigInt(order.filled_quantity);
  return (
    <Card
      title="Order Details"
      action={<OrderStatus status={order.status} />}
      className="padded order-details"
    >
      <dl className="details">
        {[
          ['Order ID', `#${order.id}`],
          ['Instrument', symbolFor(order.instrument_id)],
          ['Side', order.side],
          ['Limit Price', `${fmt(order.price_ticks)} ticks`],
          ['Original Qty', fmt(order.quantity)],
          ['Filled Qty', fmt(order.filled_quantity)],
          ['Unfilled Qty', fmt(remaining)],
          ['Submitted (UTC)', time(order.created_at, true)],
          ['Updated (UTC)', time(order.updated_at, true)],
          ['Archived', order.archived ? 'Yes' : 'No'],
        ].map(([a, b]) => (
          <div className="contents" key={a}>
            <dt>{a}</dt>
            <dd className="mono">{b}</dd>
          </div>
        ))}
      </dl>
      {['OPEN', 'PARTIAL'].includes(order.status) ? (
        <>
          <button className="button cancel-button full" onClick={() => onCancel(order)}>
            Cancel remaining {fmt(remaining)} units
          </button>
          <p className="caption" style={{ marginTop: 14 }}>
            Future cancellation settles pending fills before releasing remaining escrow. The preview
            only changes local order status.
          </p>
        </>
      ) : (
        <p className="caption">
          {order.status === 'CANCELLED'
            ? 'The unfilled portion is cancelled and is no longer resting or reserved.'
            : 'This order is terminal and cannot be cancelled.'}
        </p>
      )}
    </Card>
  );
}
