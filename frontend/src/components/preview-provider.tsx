'use client';
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  useCallback,
  type ReactNode,
} from 'react';
import type {
  AccountRole,
  FixtureState,
  Outcome,
  PreviewSession,
  InstrumentInfo,
} from '@/lib/contracts';
import { LiveConnection } from './live-provider';
import type { LiveState } from '@/lib/live/client';
import { createAuthController, type AuthState } from '@/lib/auth-state';
import { startPolling } from '@/lib/polling';
import { createRealDataServices } from '@/lib/api/client';
import * as liveAuth from '@/lib/api/auth-client';
import { createMockServices, type Services } from '@/lib/services';
import { useRouter } from 'next/navigation';
import { Empty, Notice, Skeleton } from './ui';
interface Preview {
  mock: boolean;
  session: PreviewSession | null;
  ready: boolean;
  authState: AuthState;
  retrySession: () => void;
  fixture: FixtureState;
  setFixture: (s: FixtureState) => void;
  outcome: Outcome;
  setOutcome: (s: Outcome) => void;
  instrument: InstrumentInfo | null;
  instruments: InstrumentInfo[];
  catalogLoading: boolean;
  catalogError: string;
  setInstrument: (id: number) => void;
  api: Services;
  signIn: (s: PreviewSession) => void;
  logout: (reason?: 'expired' | 'logout') => Promise<void>;
  sessionReason: 'expired' | 'logout';
  sessionGeneration: number;
  liveState: LiveState;
  revision: number;
  invalidate: () => void;
  registerResource: (refresh: () => Promise<boolean>) => () => void;
  refreshResources: () => Promise<boolean>;
}
const Context = createContext<Preview | null>(null);
const key = 'tradegraph.mock-preview.v1';
export function PreviewProvider({
  children,
  mock = false,
}: {
  children: ReactNode;
  mock?: boolean;
}) {
  const resources = useRef(new Set<() => Promise<boolean>>());
  const registerResource = useCallback((refresh: () => Promise<boolean>) => {
    resources.current.add(refresh);
    return () => {
      resources.current.delete(refresh);
    };
  }, []);
  const refreshResources = useCallback(async () => {
    const results = await Promise.allSettled([...resources.current].map((refresh) => refresh()));
    return (
      results.length > 0 && results.every((result) => result.status === 'fulfilled' && result.value)
    );
  }, []);
  const [authState, setAuthState] = useState<AuthState>({ status: 'loading' });
  const [auth] = useState(() => createAuthController(setAuthState));
  const session = authState.status === 'authenticated' ? authState.session : null;
  const ready = authState.status !== 'loading';
  const setSession = auth.accept;
  const channel = useRef<BroadcastChannel | null>(null);
  const retrySession = useCallback(() => {
    if (!mock) void auth.verify(liveAuth.session);
  }, [auth, mock]);
  const [fixture, setFixture] = useState<FixtureState>('populated'),
    [outcome, setOutcome] = useState<Outcome>('accepted'),
    [instrumentId, setInstrument] = useState(1),
    [revision, setRevision] = useState(0);
  const [sessionGeneration, setSessionGeneration] = useState(0);
  const [liveState, setLiveState] = useState<LiveState>('disconnected');
  const [sessionReason, setSessionReason] = useState<'expired' | 'logout'>('expired');
  const [instruments, setInstruments] = useState<InstrumentInfo[]>([]);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState('');
  const refs = useRef({ session, fixture, outcome });
  refs.current = { session, fixture, outcome };
  const [api] = useState(() =>
    mock
      ? createMockServices(
          () => refs.current.session,
          () => refs.current.fixture,
          () => refs.current.outcome,
        )
      : {
          ...createRealDataServices(),
          auth: {
            login: liveAuth.login,
            preview: () => {
              throw new Error('Mock login is disabled');
            },
          },
        },
  );
  useEffect(() => {
    let active = true;
    if (!session) {
      setInstruments([]);
      return;
    }
    setCatalogLoading(true);
    setCatalogError('');
    api.instruments
      .list()
      .then((catalog) => {
        if (active) setInstruments(catalog.items);
      })
      .catch((e) => {
        if (active) {
          setInstruments([]);
          setCatalogError((e as Error).message);
        }
      })
      .finally(() => {
        if (active) setCatalogLoading(false);
      });
    return () => {
      active = false;
    };
  }, [api, session, fixture]);
  useEffect(() => {
    if (!mock) {
      retrySession();
      return () => auth.cancel();
    }
    setSession(null);
    try {
      const raw = sessionStorage.getItem(key);
      if (raw) {
        const s = JSON.parse(raw) as PreviewSession;
        if (
          s &&
          s.kind === 'mock-preview' &&
          ['TRADER', 'COMPLIANCE_ADMIN'].includes(s.role) &&
          Number.isFinite(s.expiresAt) &&
          s.expiresAt > Date.now()
        )
          setSession(s);
        else sessionStorage.removeItem(key);
      }
    } catch {
      /* Storage may be unavailable; an in-memory preview still works. */
    }
  }, [mock, auth, retrySession]);
  const signIn = useCallback(
    (s: PreviewSession) => {
      setSessionGeneration((g) => g + 1);
      setSession(s);
      channel.current?.postMessage('changed');
      try {
        if (mock) sessionStorage.setItem(key, JSON.stringify(s));
      } catch {
        /* Memory-only preview. */
      }
      setFixture('populated');
    },
    [mock, auth],
  );
  const logout = useCallback(
    async (reason: 'expired' | 'logout' = 'logout') => {
      setSessionGeneration((g) => g + 1);
      setSessionReason(reason);
      if (!mock && reason === 'logout') await auth.logout(liveAuth.logout);
      else setSession(null);
      channel.current?.postMessage('changed');
      try {
        sessionStorage.removeItem(key);
      } catch {
        /* No credentials are stored. */
      }
      setFixture('populated');
    },
    [mock, auth],
  );
  useEffect(() => {
    if (mock) return;
    const bus = new BroadcastChannel('tradegraph-session');
    channel.current = bus;
    bus.onmessage = retrySession;
    const visible = () => {
      if (!document.hidden) retrySession();
    };
    document.addEventListener('visibilitychange', visible);
    return () => {
      channel.current = null;
      bus.close();
      document.removeEventListener('visibilitychange', visible);
    };
  }, [mock, retrySession]);
  useEffect(() => {
    const expired = () => {
      void logout('expired');
    };
    window.addEventListener('tradegraph:expired', expired);
    return () => window.removeEventListener('tradegraph:expired', expired);
  }, [logout]);
  useEffect(() => {
    if (!session) return;
    const timeout = setTimeout(
      () => logout('expired'),
      Math.max(0, session.expiresAt - Date.now()),
    );
    return () => clearTimeout(timeout);
  }, [session, logout]);
  return (
    <Context.Provider
      value={{
        mock,
        session,
        ready,
        authState,
        retrySession,
        fixture,
        setFixture,
        outcome,
        setOutcome,
        instrument: instruments.find((x) => x.id === instrumentId) ?? instruments[0] ?? null,
        instruments,
        catalogLoading,
        catalogError,
        setInstrument,
        api,
        signIn,
        logout,
        sessionReason,
        sessionGeneration,
        liveState,
        revision,
        invalidate: () => setRevision((r) => r + 1),
        registerResource,
        refreshResources,
      }}
    >
      {session && !mock && (
        <LiveConnection
          key={sessionGeneration}
          instrumentId={instruments.find((x) => x.id === instrumentId)?.id ?? instruments[0]?.id}
          onEvent={() => setRevision((r) => r + 1)}
          onState={setLiveState}
        />
      )}
      {children}
    </Context.Provider>
  );
}
export function usePreview() {
  const value = useContext(Context);
  if (!value) throw new Error('PreviewProvider required');
  return value;
}
export type ResourceStatus = 'INITIAL_LOADING' | 'READY' | 'REFRESHING' | 'STALE' | 'ERROR';
export function useResource<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: unknown[] = [],
  interval = 0,
) {
  const { fixture, revision, mock, session, sessionGeneration, registerResource } = usePreview();
  const scope = JSON.stringify([
    fixture,
    sessionGeneration,
    session?.role,
    session?.expiresAt,
    ...deps,
  ]);
  const [resource, setResource] = useState<{
    scope: string;
    data: T | null;
    status: ResourceStatus;
    error: string;
  }>({ scope, data: null, status: 'INITIAL_LOADING', error: '' });
  const fn = useRef(load);
  fn.current = load;
  const poll = useRef<ReturnType<typeof startPolling<T>> | null>(null);
  useEffect(() => {
    setResource((previous) =>
      previous.scope === scope
        ? previous
        : { scope, data: null, status: 'INITIAL_LOADING', error: '' },
    );
    const polling = startPolling({
      load: (signal) => fn.current(signal),
      started: () =>
        setResource((previous) => ({
          ...previous,
          status:
            previous.scope === scope && previous.data !== null ? 'REFRESHING' : 'INITIAL_LOADING',
        })),
      value: (data) => setResource({ scope, data, status: 'READY', error: '' }),
      error: (error) =>
        setResource((previous) => ({
          scope,
          data: previous.scope === scope ? previous.data : null,
          status: previous.scope === scope && previous.data !== null ? 'STALE' : 'ERROR',
          error: error instanceof Error ? error.message : 'Service unavailable',
        })),
      settled: () => {},
      interval: mock ? 0 : interval,
      hidden: () => !mock && document.hidden,
      enabled: !!session && fixture !== 'loading',
    });
    poll.current = polling;
    const unregister = interval < 0 ? () => {} : registerResource(polling.refresh);
    const visible = () => {
      if (!document.hidden) void polling.refresh();
    };
    if (interval > 0 && !mock) document.addEventListener('visibilitychange', visible);
    return () => {
      poll.current = null;
      unregister();
      polling.stop();
      document.removeEventListener('visibilitychange', visible);
    };
  }, [scope, revision, mock, session, interval, registerResource]);
  const current = resource.scope === scope && !!session;
  return {
    data: current ? resource.data : null,
    loading: !current || resource.status === 'INITIAL_LOADING',
    refreshing: current && resource.status === 'REFRESHING',
    status: current ? resource.status : ('INITIAL_LOADING' as ResourceStatus),
    error: current ? resource.error : '',
    reload: () => {
      void poll.current?.refresh();
    },
  };
}
export function InstrumentSelector() {
  const { instrument, setInstrument, instruments, catalogLoading } = usePreview();
  return (
    <label className="instrument-select">
      <span className="sr-only">Instrument</span>
      <select
        aria-label="Selected instrument"
        value={instrument?.id ?? ''}
        disabled={!instruments.length || catalogLoading}
        onChange={(e) => setInstrument(Number(e.target.value))}
      >
        {!instruments.length && <option value="">No active instruments</option>}
        {instruments.map((i) => (
          <option key={i.id} value={i.id}>
            {i.symbol}
          </option>
        ))}
      </select>
    </label>
  );
}
export function MissingInstrument() {
  const { catalogLoading, catalogError } = usePreview();
  if (catalogLoading) return <Skeleton />;
  if (catalogError) return <Notice tone="error">{catalogError}</Notice>;
  return (
    <Empty message="No active instruments are available. Trading and market queries are disabled." />
  );
}
export function RoleGuard({ role, children }: { role: AccountRole; children: ReactNode }) {
  const { session, ready, sessionReason, authState, retrySession } = usePreview();
  const router = useRouter();
  useEffect(() => {
    if (authState.status === 'unauthenticated')
      router.replace(sessionReason === 'expired' ? '/auth?reason=expired' : '/auth');
  }, [authState.status, sessionReason, router]);
  if (authState.status === 'temporarily_unavailable')
    return (
      <Notice tone="warning">
        Session service unavailable. Your login has not been discarded.{' '}
        <button className="link" onClick={retrySession}>
          Retry session
        </button>
      </Notice>
    );
  if (!ready || !session)
    return (
      <div className="loading-route" role="status">
        Loading session…
      </div>
    );
  if (session.role !== role)
    return (
      <div className="loading-route">
        <h1>Access unavailable for this role</h1>
        <p>Your authenticated role cannot open this interface.</p>
        <a
          className="link"
          href={session.role === 'TRADER' ? '/trader/dashboard' : '/admin/overview'}
        >
          Return to your workspace →
        </a>
      </div>
    );
  return children;
}
