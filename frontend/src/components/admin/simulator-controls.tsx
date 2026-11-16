'use client';
import { useEffect, useState, useRef } from 'react';
import type { Int, SimulationStart, SimulationStatus } from '@/lib/contracts';
import { fmt, integer, time } from '@/lib/exact';
import { usePreview, useResource } from '../preview-provider';
import { Badge, Button, Card, DataState, Notice, OrderStatus } from '../ui';
export function SimulatorControls() {
  const { api, instruments, mock } = usePreview();
  const [ids, setIds] = useState<number[]>([]),
    [bots, setBots] = useState('8'),
    [rate, setRate] = useState('2'),
    [duration, setDuration] = useState('300'),
    [seed, setSeed] = useState('20261115'),
    [volatility, setVolatility] = useState<SimulationStart['volatility']>('medium'),
    [local, setLocal] = useState<SimulationStatus | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [message, setMessage] = useState(''),
    [reconciling, setReconciling] = useState(false);
  const pending = useRef(false);
  const resource = useResource((signal) => api.simulator.status(signal), [], busy ? -1 : 2500);
  useEffect(() => {
    if (resource.data) {
      setLocal(resource.data);
      setReconciling(false);
    }
  }, [resource.data]);
  useEffect(() => {
    setIds((previous) => {
      const valid = previous.filter((id) => instruments.some((i) => i.id === id));
      return valid.length ? valid : instruments.length ? [instruments[0].id] : [];
    });
  }, [instruments]);
  const status = local ?? resource.data;
  const locked = busy || reconciling || !!resource.error || status?.state !== 'STOPPED';
  const start = async () => {
    if (pending.current) return;
    pending.current = true;
    setError('');
    setMessage('');
    setBusy(true);
    try {
      const config: SimulationStart = {
        instrument_ids: ids,
        bot_count: Number(integer(bots, 4n, 8n)),
        orders_per_second: Number(integer(rate, 1n, 5n)),
        max_duration_seconds: Number(integer(duration, 30n, 600n)),
        seed: integer(seed || '20261115', 0n).toString() as Int,
        volatility,
      };
      const r = await api.simulator.start(config);
      setLocal(r);
      setMessage(
        mock
          ? 'Mock simulation is RUNNING.'
          : `Backend simulator ${r.state}. Accepted orders do not guarantee executions.`,
      );
    } catch (e) {
      setError((e as Error).message);
      setReconciling(true);
    } finally {
      pending.current = false;
      setBusy(false);
      resource.reload();
    }
  };
  const stop = async () => {
    if (!status) return;
    if (pending.current) return;
    pending.current = true;
    setError('');
    setMessage('');
    setBusy(true);
    try {
      const r = await api.simulator.stop();
      setLocal(r);
      if (r.state === 'STOPPED')
        setMessage(
          mock
            ? 'Mock simulation STOPPED.'
            : 'Backend simulator STOPPED after verified cleanup. Human orders and committed history are preserved.',
        );
      else if (r.state === 'ERROR')
        setError(r.last_error ?? 'Stop failed. Operator reconciliation required.');
      else setMessage('STOPPING — cleanup is pending.');
    } catch (e) {
      setError((e as Error).message);
      setReconciling(true);
      setMessage('Stop outcome is unknown. Status is refreshing; do not assume cleanup succeeded.');
    } finally {
      pending.current = false;
      setBusy(false);
      resource.reload();
    }
  };
  return (
    <Card
      title="Live Market Simulation Controls"
      action={
        <Badge tone="blue">{mock ? 'Mock controls · non-live' : 'Live backend controls'}</Badge>
      }
      className="padded"
    >
      <DataState {...resource} retry={resource.reload}>
        {status && (
          <div className="stack">
            <fieldset className="sim-instruments" disabled={locked}>
              <legend>Instruments (select 1–3)</legend>
              {instruments.map((i) => (
                <label key={i.id}>
                  <input
                    type="checkbox"
                    checked={ids.includes(i.id)}
                    onChange={(e) =>
                      setIds((list) =>
                        e.target.checked ? [...list, i.id] : list.filter((id) => id !== i.id),
                      )
                    }
                  />
                  {i.symbol}
                </label>
              ))}
            </fieldset>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void start();
              }}
              className="stack"
            >
              <div className="sim-fields">
                {[
                  ['Bot count (4–8)', bots, setBots],
                  ['Attempts / sec (1–5)', rate, setRate],
                  ['Duration, sec (30–600)', duration, setDuration],
                  ['Seed (optional)', seed, setSeed],
                ].map(([label, value, set]) => (
                  <label className="field" key={String(label)}>
                    {String(label)}
                    <input
                      inputMode="numeric"
                      disabled={locked}
                      value={String(value)}
                      onChange={(e) => (set as (s: string) => void)(e.target.value)}
                    />
                  </label>
                ))}
                <label className="field">
                  Volatility
                  <select
                    value={volatility}
                    disabled={locked}
                    onChange={(e) => setVolatility(e.target.value as SimulationStart['volatility'])}
                  >
                    <option value="low">Low</option>
                    <option value="medium">Medium</option>
                    <option value="high">High</option>
                  </select>
                </label>
              </div>
              <div className="row-between">
                <div className="toolbar">
                  <OrderStatus status={status.state} />
                  <span className="caption">Active bots: {status.active_bots}</span>
                </div>
                <div className="toolbar">
                  {status.state === 'ERROR' && (
                    <Button
                      type="button"
                      disabled={busy}
                      onClick={async () => {
                        setBusy(true);
                        setError('');
                        try {
                          setLocal(await api.simulator.recover());
                          setMessage('Recovery verified. Simulator is STOPPED.');
                        } catch (e) {
                          setError((e as Error).message);
                        } finally {
                          setBusy(false);
                          resource.reload();
                        }
                      }}
                    >
                      Verify recovery
                    </Button>
                  )}
                  <Button variant="primary" type="submit" disabled={locked || !ids.length}>
                    Start Simulation
                  </Button>
                  <Button
                    variant="sell"
                    type="button"
                    disabled={busy || status.state !== 'RUNNING'}
                    onClick={() => void stop()}
                  >
                    {status.state === 'STOPPING' ? 'Stopping…' : 'Stop Simulation'}
                  </Button>
                </div>
              </div>
            </form>
            <div className="sim-counters">
              {[
                ['Orders attempted', status.orders_attempted],
                ['Accepted', status.orders_accepted],
                ['Rejected', status.orders_rejected],
                ['Cancelled', status.orders_cancelled],
                ['Active bot orders', status.active_bot_orders],
                ['Committed executions', status.committed_executions],
                ['Backpressure', status.backpressure_events],
              ].map(([name, value]) => (
                <div key={name}>
                  <span className="caption">{name}</span>
                  <strong className="mono">{fmt(value)}</strong>
                </div>
              ))}
            </div>
            <div className="row-between">
              <span className="caption">Last action: {time(status.last_action_at)} · UTC</span>
              <div className="toolbar">
                {Object.entries(status.derived_workers).map(([name, state]) => (
                  <Badge key={name} tone={state === 'ready' ? 'green' : 'amber'}>
                    {name}: {state}
                  </Badge>
                ))}
              </div>
            </div>
            {status.last_error && <Notice tone="error">{status.last_error}</Notice>}
            {error && <Notice tone="error">{error}</Notice>}
            {message && (
              <Notice tone={status.state === 'STOPPED' ? 'success' : 'info'}>{message}</Notice>
            )}
            <p className="caption">
              The rate caps scheduling attempts, not fills. Accepted orders are distinct from
              committed executions. Stop succeeds only at STOPPED; ERROR requires operator
              attention.
            </p>
          </div>
        )}
      </DataState>
    </Card>
  );
}
