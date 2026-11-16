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
import { createRealDataServices } from '@/lib/api/client';
import * as liveAuth from '@/lib/api/auth-client';
import { createMockServices, type Services } from '@/lib/services';
import { useRouter } from 'next/navigation';
import { Empty, Notice, Skeleton } from './ui';
interface Preview {
  mock: boolean;
  session: PreviewSession | null;
  ready: boolean;
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
  revision: number;
  invalidate: () => void;
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
  const [session, setSession] = useState<PreviewSession | null>(null),
    [ready, setReady] = useState(false),
    [fixture, setFixture] = useState<FixtureState>('populated'),
    [outcome, setOutcome] = useState<Outcome>('accepted'),
    [instrumentId, setInstrument] = useState(1),
    [revision, setRevision] = useState(0);
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
      let active = true;
      void liveAuth
        .session()
        .then((s) => {
          if (active) setSession(s);
        })
        .catch(() => {
          if (active) setSession(null);
        })
        .finally(() => {
          if (active) setReady(true);
        });
      return () => {
        active = false;
      };
    }
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
    setReady(true);
  }, [mock]);
  const signIn = useCallback(
    (s: PreviewSession) => {
      setSession(s);
      try {
        if (mock) sessionStorage.setItem(key, JSON.stringify(s));
      } catch {
        /* Memory-only preview. */
      }
      setFixture('populated');
    },
    [mock],
  );
  const logout = useCallback(
    async (reason: 'expired' | 'logout' = 'logout') => {
      if (!mock && reason === 'logout') await liveAuth.logout();
      setSessionReason(reason);
      setSession(null);
      try {
        sessionStorage.removeItem(key);
      } catch {
        /* No credentials are stored. */
      }
      setFixture('populated');
    },
    [mock],
  );
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
        revision,
        invalidate: () => setRevision((r) => r + 1),
      }}
    >
      {children}
    </Context.Provider>
  );
}
export function usePreview() {
  const value = useContext(Context);
  if (!value) throw new Error('PreviewProvider required');
  return value;
}
export function useResource<T>(
  load: (signal: AbortSignal) => Promise<T>,
  deps: unknown[] = [],
  interval = 0,
) {
  const { fixture, revision, mock, session } = usePreview();
  const [data, setData] = useState<T | null>(null),
    [loading, setLoading] = useState(true),
    [error, setError] = useState(''),
    [nonce, setNonce] = useState(0);
  const scope = JSON.stringify([fixture, session?.role, session?.expiresAt, ...deps]);
  const previousScope = useRef<string | null>(null);
  const fn = useRef(load);
  fn.current = load;
  useEffect(() => {
    let active = true,
      pending = false,
      failures = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    if (previousScope.current !== scope) {
      setData(null);
      setLoading(true);
      previousScope.current = scope;
    }
    setError('');
    const run = async () => {
      if (!active || pending || !session || fixture === 'loading' || interval < 0) return;
      if (document.hidden && !mock) {
        timer = setTimeout(run, Math.max(interval, 1000));
        return;
      }
      pending = true;
      try {
        const value = await fn.current(controller.signal);
        if (active) {
          setData(value);
          setError('');
          failures = 0;
        }
      } catch (e) {
        if (active) {
          setError(e instanceof Error ? e.message : 'Service unavailable');
          failures++;
        }
      } finally {
        pending = false;
        if (active) {
          setLoading(false);
          if (!mock && interval > 0)
            timer = setTimeout(run, Math.min(interval * 2 ** Math.min(failures, 4), 30000));
        }
      }
    };
    void run();
    const visible = () => {
      if (!document.hidden && !pending) {
        clearTimeout(timer);
        void run();
      }
    };
    if (interval > 0 && !mock) document.addEventListener('visibilitychange', visible);
    return () => {
      active = false;
      controller.abort();
      clearTimeout(timer);
      document.removeEventListener('visibilitychange', visible);
    };
  }, [fixture, revision, nonce, mock, session, interval, ...deps]);
  return { data: session ? data : null, loading, error, reload: () => setNonce((x) => x + 1) };
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
  const { session, ready, sessionReason } = usePreview();
  const router = useRouter();
  useEffect(() => {
    if (ready && !session)
      router.replace(sessionReason === 'expired' ? '/auth?reason=expired' : '/auth');
  }, [ready, session, sessionReason, router]);
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
