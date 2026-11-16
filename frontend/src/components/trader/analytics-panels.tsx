'use client';
import { useEffect, useState, useRef } from 'react';
import type { Analytics, Int } from '@/lib/contracts';
import { decimal, fmt, integer, time, MAX_PRICE } from '@/lib/exact';
import { usePreview } from '../preview-provider';
import { Button, Card, Notice } from '../ui';
export function VwapPanel({ analytics, symbol }: { analytics: Analytics; symbol: string }) {
  return (
    <Card className="padded vwap-panel">
      <div className="row-between">
        <h2>VWAP — {symbol}</h2>
        <span className="caption">{time(analytics.as_of)} UTC</span>
      </div>
      <strong className="mono">{decimal(analytics.vwap_ticks)}</strong>
      <p className="caption">
        Quantity-weighted average of {analytics.window_fills} observed fills in the last-100-fill
        window · cumulative-prefix ring buffer
      </p>
      <p className="caption" style={{ marginTop: 10 }}>
        Value in ticks.{' '}
        {analytics.vwap_ticks === null
          ? 'No settled executions yet.'
          : 'Analytics from settled executions.'}
      </p>
    </Card>
  );
}
export function PriceBandPanel() {
  const { api, instrument, fixture } = usePreview();
  const [lower, setLower] = useState('0'),
    [upper, setUpper] = useState(MAX_PRICE.toString()),
    [result, setResult] = useState<Analytics | null>(null),
    [bounds, setBounds] = useState(['0', MAX_PRICE.toString()]),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  useEffect(() => {
    request.current?.abort();
    setResult(null);
    setError('');
    return () => request.current?.abort();
  }, [instrument?.id, fixture]);
  return (
    <Card title="Price-Band Executed Volume" className="padded">
      <form
        className="stack"
        onSubmit={async (e) => {
          e.preventDefault();
          if (busy) return;
          request.current?.abort();
          const controller = new AbortController();
          request.current = controller;
          setError('');
          setBusy(true);
          try {
            if (!instrument) throw new Error('Select an active instrument.');
            if (integer(lower, 0n, MAX_PRICE) > integer(upper, 0n, MAX_PRICE))
              throw new Error('Lower bound must not exceed upper bound.');
            const r = await api.market.analytics(
              instrument.symbol,
              lower as Int,
              upper as Int,
              controller.signal,
            );
            if (controller.signal.aborted) return;
            setResult(r);
            setBounds([lower, upper]);
          } catch (e) {
            if (!controller.signal.aborted) setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <div className="toolbar">
          <label className="field narrow">
            Lower ticks
            <input
              value={lower}
              onChange={(e) => setLower(e.target.value)}
              inputMode="numeric"
              required
            />
          </label>
          <label className="field narrow">
            Upper ticks
            <input
              value={upper}
              onChange={(e) => setUpper(e.target.value)}
              inputMode="numeric"
              required
            />
          </label>
          <Button variant="primary" type="submit" disabled={busy} style={{ alignSelf: 'flex-end' }}>
            {busy ? 'Calculating…' : 'Calculate'}
          </Button>
        </div>
        <div className="band-result row-between">
          <span>Executed volume {result ? `in [${bounds[0]}, ${bounds[1]}]` : ''}</span>
          <strong className="mono">
            {result ? `${fmt(result.band_volume)} units` : 'Run query'}
          </strong>
        </div>
        {error && <Notice tone="error">{error}</Notice>}
        <p className="caption">
          Fenwick-indexed executed volume — distinct from resting order-book quantity.
        </p>
      </form>
    </Card>
  );
}
