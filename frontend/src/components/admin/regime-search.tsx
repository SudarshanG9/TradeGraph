'use client';
import { useEffect, useRef, useState } from 'react';
import type { Features, Similar } from '@/lib/contracts';
import { currentFeatures } from '@/lib/mock/fixtures';
import { InstrumentSelector, usePreview } from '../preview-provider';
import { Button, Card, Notice, Segmented } from '../ui';
export function RegimeSearch({
  onResult,
  onBusy,
}: {
  onResult: (r: Similar | null) => void;
  onBusy: (b: boolean) => void;
}) {
  const { api, instrument, fixture, mock } = usePreview();
  const [mode, setMode] = useState<'current' | 'custom'>('current'),
    [values, setValues] = useState(
      mock ? currentFeatures.map(String) : ['1', '0', '0', '0', '0', '0'],
    ),
    [k, setK] = useState('10'),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  const requestSequence = useRef(0);
  useEffect(() => {
    requestSequence.current++;
    setBusy(false);
    onBusy(false);
    onResult(null);
    setError('');
  }, [instrument?.id, fixture, mode]);
  const labels = [
    'Bid–ask spread',
    'Order-book imbalance',
    'VWAP drift',
    'Trade velocity',
    'Depth ratio',
    'Realized volatility',
  ];
  return (
    <Card className="padded">
      <form
        className="stack"
        onSubmit={async (e) => {
          e.preventDefault();
          const request = ++requestSequence.current;
          setError('');
          setBusy(true);
          onBusy(true);
          try {
            if (!instrument) throw new Error('Select an active instrument.');
            const count = Number(k);
            if (!Number.isInteger(count) || count < 1 || count > 100)
              throw new Error('Result limit must be 1–100.');
            const features = values.map((v) => {
              if (!v.trim()) throw new Error('Enter all six feature values.');
              return Number(v);
            }) as Features;
            if (
              mode === 'custom' &&
              (!features.every(Number.isFinite) || !features.some((v) => v !== 0))
            )
              throw new Error('Enter six finite values with a nonzero vector.');
            const r = await api.regimes.similar(
              mode === 'current'
                ? { instrument_id: instrument.id, current: true, k: count }
                : { instrument_id: instrument.id, features, k: count },
            );
            if (request === requestSequence.current) onResult(r);
          } catch (e) {
            if (request !== requestSequence.current) return;
            onResult(null);
            setError((e as Error).message);
          } finally {
            if (request === requestSequence.current) {
              setBusy(false);
              onBusy(false);
            }
          }
        }}
      >
        <div className="row-between">
          <div className="toolbar">
            <InstrumentSelector />
            <Segmented
              label="Feature source"
              value={mode}
              onChange={setMode}
              options={[
                { value: 'current', label: 'Use Current Market Features' },
                { value: 'custom', label: 'Custom Feature Vector' },
              ]}
            />
          </div>
          <div className="toolbar">
            <label className="field" style={{ width: 70 }}>
              Results
              <input value={k} onChange={(e) => setK(e.target.value)} inputMode="numeric" />
            </label>
            <Button
              variant="primary"
              disabled={busy || fixture === 'loading' || !instrument}
              type="submit"
            >
              {busy ? 'Searching…' : 'Find Similar Regimes'}
            </Button>
          </div>
        </div>
        <div className="grid-3 feature-grid">
          {labels.map((label, i) => (
            <label className="field" key={label}>
              {label.toUpperCase()}
              <input
                className="mono"
                disabled={mode === 'current'}
                aria-label={label}
                placeholder={mode === 'current' ? 'Computed by backend on query' : 'Feature value'}
                value={mode === 'current' ? (mock ? String(currentFeatures[i]) : '') : values[i]}
                onChange={(e) =>
                  setValues((old) => old.map((v, j) => (j === i ? e.target.value : v)))
                }
              />
            </label>
          ))}
        </div>
        {error && (
          <Notice tone="error">
            {error === 'NO_MARKET_OBSERVATIONS'
              ? 'No market observations are available for the current-feature query.'
              : error}
          </Notice>
        )}
        <p className="caption">
          {mock
            ? 'Demo current feature vector.'
            : 'Current mode captures backend observations on explicit query. The API does not return a standalone current vector.'}{' '}
          Results are retrieved on demand.
        </p>
      </form>
    </Card>
  );
}
