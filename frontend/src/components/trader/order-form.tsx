'use client';
import { ApiError } from '@/lib/api/errors';
import Link from 'next/link';
import { useState, useRef, useEffect } from 'react';
import type { Int, NewOrder } from '@/lib/contracts';
import { fmt, validateOrder } from '@/lib/exact';
import { usePreview } from '../preview-provider';
import { Button, Card, Notice, Segmented } from '../ui';
export function OrderForm() {
  const { instrument, api, invalidate, outcome, mock, session } = usePreview();
  const [side, setSide] = useState<'BUY' | 'SELL'>('BUY'),
    [price, setPrice] = useState('100'),
    [quantity, setQuantity] = useState(instrument?.lot_size ?? ''),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState(''),
    [error, setError] = useState('');
  const pending = useRef(false);
  const [uncertain, setUncertain] = useState(false);
  useEffect(() => {
    let active = true;
    void api.orders
      .pending()
      .then((value) => {
        if (active) setUncertain(value);
      })
      .catch(() => {
        if (active) setUncertain(true);
      });
    return () => {
      active = false;
    };
  }, [api, session]);
  if (!instrument) return null;
  const order: NewOrder = {
    instrument_id: instrument.id,
    side,
    price_ticks: price as Int,
    quantity: quantity as Int,
  };
  let estimate = '—',
    validation = '';
  try {
    estimate = fmt(validateOrder(order, instrument));
  } catch (e) {
    validation = (e as Error).message;
  }
  return (
    <Card title="Place Order" className="order-form">
      <form
        className="stack padded"
        onSubmit={async (e) => {
          e.preventDefault();
          if (pending.current || uncertain) return;
          setMessage('');
          setError('');
          if (validation) {
            setError(validation);
            return;
          }
          pending.current = true;
          setBusy(true);
          try {
            const r = await api.orders.submit(order);
            setMessage(
              mock
                ? `Mock order #${r.order_id}: ${outcome === 'partial' ? 'partial fill preview' : outcome === 'filled' ? 'filled preview' : 'accepted preview'}. No real order was placed. Acceptance is not settlement.`
                : `Order #${r.order_id} accepted. Matching and settlement are asynchronous; refreshed orders and executions show the final result.`,
            );
            invalidate();
          } catch (e) {
            setError((e as Error).message);
            if (e instanceof ApiError && e.uncertain) {
              setUncertain(true);
              invalidate();
            }
          } finally {
            pending.current = false;
            setBusy(false);
          }
        }}
      >
        <div className="buy-sell">
          <Segmented
            value={side}
            onChange={setSide}
            label="Order side"
            options={[
              { value: 'BUY', label: 'BUY' },
              { value: 'SELL', label: 'SELL' },
            ]}
          />
        </div>
        <label className="field">
          Instrument
          <input value={instrument.symbol} disabled />
        </label>
        <label className="field">
          Limit Price (ticks)
          <input
            className="mono"
            inputMode="numeric"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            required
            aria-describedby="order-estimate"
          />
        </label>
        <label className="field">
          Quantity (units)
          <input
            className="mono"
            inputMode="numeric"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value as Int)}
            required
          />
        </label>
        <p className="caption" id="order-estimate">
          Estimated notional (est.): <span className="mono">{estimate}</span> minor units. Fees
          excluded.
        </p>
        <Button
          variant={side === 'BUY' ? 'buy' : 'sell'}
          disabled={busy || uncertain}
          type="submit"
        >
          {busy ? 'Submitting…' : `Submit ${side} Order${mock ? ' · Demo' : ''}`}
        </Button>
        {error && <Notice tone="error">{error}</Notice>}
        {uncertain && (
          <Notice tone="warning">
            Submission is locked to prevent duplicate orders.{' '}
            <Link className="link" href="/trader/orders">
              Review persisted orders
            </Link>{' '}
            and account reservations. Check the accepted outcome or retry the original saved request
            with its original key.
          </Notice>
        )}
        {uncertain && (
          <div className="toolbar">
            <Button
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const result = await api.orders.reconcile();
                  if (result) {
                    setUncertain(false);
                    setError('');
                    setMessage(`Order #${result.order_id} accepted.`);
                    invalidate();
                  } else setError('Outcome remains unresolved. The original request is retained.');
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setBusy(false);
                }
              }}
            >
              Check outcome
            </Button>
            <Button
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  const result = await api.orders.retry();
                  setUncertain(false);
                  setError('');
                  setMessage(`Order #${result.order_id} accepted.`);
                  invalidate();
                } catch (e) {
                  setError((e as Error).message);
                  setUncertain(await api.orders.pending().catch(() => true));
                } finally {
                  setBusy(false);
                }
              }}
            >
              Retry original request
            </Button>
          </div>
        )}
        {message && <Notice tone="success">{message}</Notice>}
        <p className="caption">
          Both BUY and SELL reserve cash in the synthetic collateral model.{' '}
          {mock
            ? 'Demo actions update local history only.'
            : 'Backend collateral checks and settlement determine actual balances.'}
        </p>
      </form>
    </Card>
  );
}
