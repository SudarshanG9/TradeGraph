import { decodeEvent, type LiveEvent } from './protocol';
export type LiveState = 'disconnected' | 'connecting' | 'resyncing' | 'live';
export interface LiveSocket {
  readyState: number;
  onopen: ((event: Event) => void) | null;
  onmessage: ((event: MessageEvent) => void) | null;
  onclose: ((event: CloseEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  send: (data: string) => void;
  close: () => void;
}
/** One owner per authenticated provider. No mutation is ever submitted here. */
export function createLiveClient(options: {
  ticket: (signal: AbortSignal) => Promise<{ ticket: string; path: string }>;
  socket: (path: string, protocols: string[]) => LiveSocket;
  state: (state: LiveState) => void;
  event: (event: LiveEvent) => void;
  retryMs?: number;
  random?: () => number;
}) {
  let stopped = true,
    generation = 0,
    attempts = 0,
    sequence = 0,
    epoch = '';
  let connection: LiveSocket | undefined;
  let controller: AbortController | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let heartbeat: ReturnType<typeof setTimeout> | undefined;
  let instruments: number[] = [];
  const versions = new Map<number, { epoch: string; version: number }>();
  const executions = new Set<string>();
  const listeners = new Set<(event: LiveEvent) => void>();
  const diagnostics = { reconnects: 0, gaps: 0 };
  const state = (value: LiveState) => {
    if (!stopped) options.state(value);
  };
  const close = () => {
    clearTimeout(heartbeat);
    if (connection) {
      connection.onopen = null;
      connection.onmessage = null;
      connection.onclose = null;
      connection.onerror = null;
      connection.close();
      connection = undefined;
    }
  };
  const reconnect = () => {
    if (stopped) return;
    generation++;
    controller?.abort();
    close();
    state('disconnected');
    clearTimeout(timer);
    diagnostics.reconnects++;
    const delay =
      Math.min((options.retryMs ?? 500) * 2 ** Math.min(attempts++, 6), 30000) *
      (0.8 + 0.4 * (options.random ?? Math.random)());
    timer = setTimeout(() => void connect(), delay);
  };
  const watchdog = () => {
    clearTimeout(heartbeat);
    heartbeat = setTimeout(reconnect, 35000);
  };
  const notify = (event: LiveEvent) => {
    options.event(event);
    for (const listener of listeners) listener(event);
  };
  async function connect() {
    if (stopped) return;
    const current = ++generation;
    state('connecting');
    controller = new AbortController();
    try {
      const ticket = await options.ticket(controller.signal);
      if (stopped || current !== generation) return;
      sequence = 0;
      epoch = '';
      versions.clear();
      executions.clear();
      const ws = (connection = options.socket(ticket.path, [
        'tradegraph.v1',
        'ticket.' + ticket.ticket,
      ]));
      ws.onopen = () => {
        if (current !== generation || stopped) return;
        state('resyncing');
        watchdog();
        if (instruments.length)
          ws.send(JSON.stringify({ type: 'subscribe', instrument_ids: instruments }));
      };
      ws.onmessage = (message) => {
        if (current !== generation || stopped) return;
        watchdog();
        try {
          const value = JSON.parse(message.data);
          if (value?.type === 'ping') {
            ws.send(JSON.stringify({ type: 'pong' }));
            return;
          }
          const event = decodeEvent(value);
          if (epoch === event.epoch && event.sequence <= sequence) return;
          const gap = !!epoch && (epoch !== event.epoch || event.sequence !== sequence + 1);
          epoch = event.epoch;
          sequence = event.sequence;
          if (gap) {
            diagnostics.gaps++;
            state('resyncing');
            notify({ ...event, type: 'resync.required' });
          }
          if (event.type === 'book.changed') {
            if (!instruments.includes(event.instrument_id!)) return;
            const previous = versions.get(event.instrument_id!);
            if (previous?.epoch === event.epoch && previous.version >= event.version!) return;
            versions.set(event.instrument_id!, { epoch: event.epoch, version: event.version! });
          }
          if (event.type === 'trade.committed') {
            if (!instruments.includes(event.instrument_id!)) return;
            if (executions.has(event.execution_id!)) return;
            executions.add(event.execution_id!);
            if (executions.size > 256) executions.delete(executions.values().next().value!);
          }
          if (event.type === 'resync.required' || event.type === 'service.degraded')
            state('resyncing');
          notify(event);
        } catch {
          reconnect();
        }
      };
      ws.onclose = reconnect;
      ws.onerror = reconnect;
    } catch {
      if (current === generation) reconnect();
    }
  }
  return {
    diagnostics,
    start: () => {
      if (!stopped) return;
      stopped = false;
      void connect();
    },
    stop: () => {
      stopped = true;
      generation++;
      controller?.abort();
      clearTimeout(timer);
      close();
      versions.clear();
      executions.clear();
      listeners.clear();
      options.state('disconnected');
    },
    subscribe: (listener: (event: LiveEvent) => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    synchronized: () => {
      if (connection?.readyState === 1) {
        attempts = 0;
        state('live');
      }
    },
    instruments: (ids: number[]) => {
      const next = [...new Set(ids)];
      if (next.length === instruments.length && next.every((id) => instruments.includes(id)))
        return;
      if (connection?.readyState === 1) {
        if (instruments.length)
          connection.send(JSON.stringify({ type: 'unsubscribe', instrument_ids: instruments }));
        if (next.length)
          connection.send(JSON.stringify({ type: 'subscribe', instrument_ids: next }));
      }
      instruments = next;
      versions.clear();
      state('resyncing');
    },
  };
}
