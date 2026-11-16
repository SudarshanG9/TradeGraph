'use client';
import { useEffect, useRef } from 'react';
import type { LiveEvent } from '@/lib/live/protocol';
import { createLiveClient, type LiveState } from '@/lib/live/client';
import { schemas } from '@/lib/api/schema';
import { ApiError } from '@/lib/api/errors';
export function LiveConnection({
  instrumentId,
  onEvent,
  onState,
}: {
  instrumentId?: number;
  onEvent: (event?: LiveEvent) => Promise<boolean>;
  onState: (state: LiveState) => void;
}) {
  const event = useRef(onEvent);
  event.current = onEvent;
  const state = useRef(onState);
  state.current = onState;
  const client = useRef<ReturnType<typeof createLiveClient> | null>(null);
  useEffect(() => {
    let active = true,
      invalidation = 0;
    const synchronize = async (event?: LiveEvent) => {
      const current = ++invalidation;
      const success = await eventRef(event);
      if (active && current === invalidation && success) live.synchronized();
    };
    const eventRef = (value?: LiveEvent) => event.current(value);
    const live = createLiveClient({
      ticket: async (signal) => {
        const response = await fetch('/api/live/ticket', {
          method: 'POST',
          credentials: 'same-origin',
          cache: 'no-store',
          headers: { 'X-TradeGraph-Request': '1' },
          signal: AbortSignal.any([signal, AbortSignal.timeout(8000)]),
        });
        if (!response.ok) {
          if (response.status === 401) window.dispatchEvent(new Event('tradegraph:expired'));
          throw new ApiError(response.status, 'LIVE_AUTH_UNAVAILABLE');
        }
        return schemas.liveTicket(await response.json());
      },
      socket: (path, protocols) =>
        new WebSocket(
          (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + path,
          protocols,
        ),
      state: (value) => {
        state.current(value);
        console.info(
          JSON.stringify({
            component: 'live',
            state: value,
            reconnects: live.diagnostics.reconnects,
            gaps: live.diagnostics.gaps,
          }),
        );
      },
      event: (event) => {
        void synchronize(event);
      },
    });
    client.current = live;
    live.start();
    const resync = setInterval(() => {
      void synchronize();
    }, 15000);
    return () => {
      clearInterval(resync);
      active = false;
      client.current = null;
      live.stop();
    };
  }, []);
  useEffect(() => client.current?.instruments(instrumentId ? [instrumentId] : []), [instrumentId]);
  return null;
}
