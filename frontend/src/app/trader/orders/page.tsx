'use client';
import { useState } from 'react';
import type { Int, OrderSummary } from '@/lib/contracts';
import { usePreview, useResource } from '@/components/preview-provider';
import { DataState, Heading, Notice, Pagination } from '@/components/ui';
import { OrderHistory, OrderDetails } from '@/components/trader/order-history';
import { CancelDialog } from '@/components/trader/cancel-dialog';
export default function Orders() {
  const { api, invalidate } = usePreview();
  const [filter, setFilter] = useState('ALL'),
    [cursors, setCursors] = useState<(Int | undefined)[]>([undefined]),
    [selectedId, setSelectedId] = useState<Int | null>(null),
    [cancel, setCancel] = useState<OrderSummary | null>(null),
    [message, setMessage] = useState('');
  const cursor = cursors.at(-1);
  const r = useResource(() => api.orders.list({ limit: 5, before_id: cursor }), [cursor]);
  const rows = r.data?.items.filter((o) => filter === 'ALL' || o.status === filter) ?? [];
  const selected = rows.find((o) => o.id === selectedId) ?? rows[0] ?? null;
  return (
    <>
      <Heading
        title="My Orders"
        description="Full demo order history, including archived and settled orders."
      />
      <div className="stack">
        <div className="filter-pills" role="group" aria-label="Order status filter">
          {[
            ['ALL', 'All'],
            ['OPEN', 'Open'],
            ['PARTIAL', 'Partially Filled'],
            ['FILLED', 'Filled'],
            ['CANCELLED', 'Cancelled'],
          ].map(([v, l]) => (
            <button key={v} aria-pressed={filter === v} onClick={() => setFilter(v)}>
              {l}
            </button>
          ))}
        </div>
        {message && <Notice tone="success">{message}</Notice>}
        <DataState {...r} retry={r.reload}>
          <div className="orders-grid">
            <OrderHistory
              orders={rows}
              selected={selected?.id ?? null}
              onSelect={(o) => setSelectedId(o.id)}
              onCancel={setCancel}
            >
              <Pagination
                loading={r.loading}
                canPrevious={cursors.length > 1}
                canNext={!!r.data?.next_before_id}
                previous={() => setCursors((c) => c.slice(0, -1))}
                next={() => {
                  if (r.data?.next_before_id) setCursors((c) => [...c, r.data!.next_before_id!]);
                }}
              />
            </OrderHistory>
            <OrderDetails order={selected} onCancel={setCancel} />
          </div>
        </DataState>
      </div>
      {cancel && (
        <CancelDialog
          order={cancel}
          onClose={() => setCancel(null)}
          onDone={() => {
            setMessage(`Demo order #${cancel.id} cancelled locally. No transaction was committed.`);
            setCancel(null);
            invalidate();
          }}
        />
      )}
    </>
  );
}
