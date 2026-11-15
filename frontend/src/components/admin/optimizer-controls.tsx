'use client';
import { useEffect, useState } from 'react';
import type { Int, Optimizer, Scenario } from '@/lib/contracts';
import { integer } from '@/lib/exact';
import { catalog } from '@/lib/mock/fixtures';
import { usePreview } from '../preview-provider';
import { Button, Card, Notice, Segmented } from '../ui';
export function OptimizerControls({
  onResult,
  onBusy,
}: {
  onResult: (r: Optimizer | null) => void;
  onBusy: (b: boolean) => void;
}) {
  const { api, fixture } = usePreview();
  const [scenario, setScenario] = useState<Scenario>('price_band'),
    [id, setId] = useState(1),
    [lower, setLower] = useState('95'),
    [upper, setUpper] = useState('105'),
    [error, setError] = useState(''),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    onResult(null);
    setError('');
  }, [fixture, scenario]);
  return (
    <Card className="padded">
      <form
        className="stack"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          onBusy(true);
          setError('');
          try {
            if (scenario === 'price_band' && integer(lower) > integer(upper))
              throw new Error('Lower bound must not exceed upper bound.');
            onResult(await api.optimizer.compare(scenario, id, lower as Int, upper as Int));
          } catch (e) {
            setError((e as Error).message);
            onResult(null);
          } finally {
            setBusy(false);
            onBusy(false);
          }
        }}
      >
        <div className="optimizer-toolbar">
          <Segmented
            value={scenario}
            onChange={setScenario}
            label="Query scenario"
            options={[
              { value: 'price_band', label: 'Price Band' },
              { value: 'recent_executions', label: 'Recent Executions' },
            ]}
          />
          <div className="toolbar">
            <label className="field">
              Instrument ID
              <select
                disabled={scenario === 'recent_executions'}
                value={id}
                onChange={(e) => setId(Number(e.target.value))}
              >
                {catalog.items.map((i) => (
                  <option value={i.id} key={i.id}>
                    {i.id} · {i.symbol}
                  </option>
                ))}
              </select>
            </label>
            <label className="field narrow">
              Lower Ticks
              <input
                disabled={scenario === 'recent_executions'}
                value={lower}
                inputMode="numeric"
                onChange={(e) => setLower(e.target.value)}
              />
            </label>
            <label className="field narrow">
              Upper Ticks
              <input
                disabled={scenario === 'recent_executions'}
                value={upper}
                inputMode="numeric"
                onChange={(e) => setUpper(e.target.value)}
              />
            </label>
          </div>
          <Button variant="primary" type="submit" disabled={busy || fixture === 'loading'}>
            {busy ? 'Comparing…' : 'Compare Plans'}
          </Button>
        </div>
        {scenario === 'recent_executions' && (
          <p className="caption">
            Recent Executions counts executions in the last 10 minutes across all instruments.
            Instrument and price parameters are unused.
          </p>
        )}
        {error && <Notice tone="error">{error}</Notice>}
      </form>
    </Card>
  );
}
