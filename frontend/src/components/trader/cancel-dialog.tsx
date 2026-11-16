'use client';
import { ApiError } from '@/lib/api/errors';
import { useState, useRef, useEffect } from 'react';
import type { OrderSummary } from '@/lib/contracts';
import { fmt } from '@/lib/exact';
import { usePreview } from '../preview-provider';
import { Button, Modal, Notice } from '../ui';
export function CancelDialog({
  order,
  onClose,
  onDone,
}: {
  order: OrderSummary;
  onClose: () => void;
  onDone: () => void;
}) {
  const { api, mock, invalidate } = usePreview(),
    [busy, setBusy] = useState(false),
    [error, setError] = useState('');
  const pending = useRef(false);
  const [uncertain, setUncertain] = useState(false);
  useEffect(() => {
    let active = true;
    void api.orders
      .cancelPending(order.trader_id, order.id)
      .then((value) => {
        if (active) setUncertain(value);
      })
      .catch(() => {
        if (active) setUncertain(true);
      });
    return () => {
      active = false;
    };
  }, [api, order.trader_id, order.id]);
  return (
    <Modal
      title={`Cancel order #${order.id}?`}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <p>
        Cancel the remaining {fmt(BigInt(order.quantity) - BigInt(order.filled_quantity))} units.{' '}
        {mock
          ? 'This is a local preview.'
          : 'The backend waits for pending settlement and releases eligible remaining reservations.'}
      </p>
      {error && <Notice tone="error">{error}</Notice>}
      {uncertain && (
        <Notice tone="warning">
          A cancellation outcome is unresolved. Check the order before cancelling again.
        </Notice>
      )}
      {uncertain && (
        <Button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const row = await api.orders.reconcileCancel(order.trader_id, order.id);
              setUncertain(false);
              setError('');
              invalidate();
              if (row.status === 'CANCELLED' || row.status === 'FILLED') onDone();
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          Check cancellation outcome
        </Button>
      )}
      <div className="toolbar" style={{ justifyContent: 'flex-end', marginTop: 16 }}>
        <Button onClick={onClose} disabled={busy}>
          Keep order
        </Button>
        <Button
          variant="sell"
          disabled={busy || uncertain}
          onClick={async () => {
            if (pending.current || uncertain) return;
            pending.current = true;
            setBusy(true);
            try {
              await api.orders.cancel(order.id);
              onDone();
            } catch (e) {
              setError((e as Error).message);
              if (e instanceof ApiError && e.uncertain) setUncertain(true);
              invalidate();
            } finally {
              pending.current = false;
              setBusy(false);
            }
          }}
        >
          {busy
            ? 'Cancellation pending…'
            : mock
              ? 'Confirm demo cancellation'
              : 'Confirm cancellation'}
        </Button>
      </div>
    </Modal>
  );
}
