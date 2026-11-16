import type { PreviewSession } from './contracts';
import { ApiError } from './api/errors';
export type AuthState =
  | { status: 'loading' }
  | { status: 'authenticated'; session: PreviewSession }
  | { status: 'unauthenticated' }
  | { status: 'temporarily_unavailable'; code: string };

/** A newer login, logout or verification always wins over older asynchronous work. */
export function createAuthController(change: (state: AuthState) => void) {
  let generation = 0;
  const failure = (error: unknown): AuthState =>
    error instanceof ApiError && error.status === 401
      ? { status: 'unauthenticated' }
      : {
          status: 'temporarily_unavailable',
          code: error instanceof ApiError ? error.code : 'SESSION_UNAVAILABLE',
        };
  return {
    cancel: () => {
      generation++;
    },
    accept: (session: PreviewSession | null) => {
      generation++;
      change(session ? { status: 'authenticated', session } : { status: 'unauthenticated' });
    },
    verify: async (load: () => Promise<PreviewSession | null>) => {
      const current = ++generation;
      change({ status: 'loading' });
      try {
        const session = await load();
        if (current === generation)
          change(session ? { status: 'authenticated', session } : { status: 'unauthenticated' });
      } catch (error) {
        if (current === generation) change(failure(error));
      }
    },
    logout: async (remove: () => Promise<void>) => {
      const current = ++generation;
      change({ status: 'loading' });
      try {
        await remove();
        if (current === generation) change({ status: 'unauthenticated' });
      } catch (error) {
        if (current === generation) change(failure(error));
        throw error;
      }
    },
  };
}
