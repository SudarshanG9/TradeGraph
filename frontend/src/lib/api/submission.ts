import { ApiError } from './errors';
import type { AcceptedOrder, NewOrder, RequestOutcome } from '../contracts';
type IntentStorage = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>;
export type SubmissionState = 'SUBMITTING' | 'UNCERTAIN' | 'RECONCILING' | 'RESOLVED' | 'BLOCKED';
export interface PendingSubmission {
  key: string;
  scope: string;
  order: NewOrder | null;
  submittedAt: number;
  state: SubmissionState;
}
/** Never discard an unresolved financial intent, including the previous v1 gate. */
export function createSubmissionTracker(storage: IntentStorage) {
  const name = (scope: string) => `tradegraph.order-intent.v2.${scope}`;
  const read = (scope: string): PendingSubmission | null => {
    const raw = storage.getItem(name(scope));
    if (raw) {
      const value = JSON.parse(raw) as PendingSubmission;
      if (value.scope !== scope || !value.key || !value.state)
        throw new ApiError(409, 'ORDER_RECONCILIATION_REQUIRED', true);
      return value;
    }
    const legacy = storage.getItem('tradegraph.uncertain-order.v1');
    return legacy ? { key: legacy, scope, order: null, submittedAt: 0, state: 'BLOCKED' } : null;
  };
  const write = (value: PendingSubmission) =>
    storage.setItem(name(value.scope), JSON.stringify(value));
  const resolve = (intent: PendingSubmission) => {
    write({ ...intent, state: 'RESOLVED' });
    storage.removeItem(name(intent.scope));
    if (storage.getItem('tradegraph.uncertain-order.v1') === intent.key)
      storage.removeItem('tradegraph.uncertain-order.v1');
  };
  const send = async (
    intent: PendingSubmission,
    dispatch: (key: string, order: NewOrder) => Promise<AcceptedOrder>,
    retry = false,
  ) => {
    if (!intent.order) throw new ApiError(409, 'ORDER_RECONCILIATION_REQUIRED', true);
    write({ ...intent, state: 'SUBMITTING' });
    try {
      const result = await dispatch(intent.key, intent.order);
      resolve(intent);
      return result;
    } catch (e) {
      if (!retry && e instanceof ApiError && !e.uncertain && e.code !== 'DUPLICATE_REQUEST')
        resolve(intent);
      else
        write({
          ...intent,
          state: e instanceof ApiError && e.code === 'DUPLICATE_REQUEST' ? 'BLOCKED' : 'UNCERTAIN',
        });
      throw e;
    }
  };
  return {
    getPendingSubmission: read,
    async beginSubmission(
      scope: string,
      order: NewOrder,
      dispatch: (key: string, order: NewOrder) => Promise<AcceptedOrder>,
    ) {
      if (read(scope)) throw new ApiError(409, 'ORDER_RECONCILIATION_REQUIRED', true);
      const intent: PendingSubmission = {
        key: crypto.randomUUID(),
        scope,
        order: { ...order },
        submittedAt: Date.now(),
        state: 'SUBMITTING',
      };
      return send(intent, dispatch);
    },
    async retrySubmission(
      scope: string,
      dispatch: (key: string, order: NewOrder) => Promise<AcceptedOrder>,
    ) {
      const intent = read(scope);
      if (!intent || intent.state === 'SUBMITTING' || intent.state === 'RECONCILING')
        throw new ApiError(409, 'ORDER_RECONCILIATION_REQUIRED', true);
      return send(intent, dispatch, true);
    },
    async reconcileSubmission(scope: string, lookup: (key: string) => Promise<RequestOutcome>) {
      const intent = read(scope);
      if (!intent) return null;
      write({ ...intent, state: 'RECONCILING' });
      try {
        const outcome = await lookup(intent.key);
        if (outcome.trader_id !== scope) throw new ApiError(409, 'ACCOUNT_CHANGED', true);
        if (outcome.status === 'ACCEPTED' && outcome.accepted_order) {
          resolve(intent);
          return outcome.accepted_order;
        }
        write({ ...intent, state: 'UNCERTAIN' });
        return null;
      } catch (e) {
        write({ ...intent, state: 'UNCERTAIN' });
        throw e;
      }
    },
  };
}

/** Cancellation has a separate per-account/order intent. A status read never resends it. */
export function createCancellationTracker(storage: IntentStorage) {
  const name = async (scope: string, id: string) => {
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(scope));
    const opaque = Array.from(new Uint8Array(digest), (n) => n.toString(16).padStart(2, '0')).join(
      '',
    );
    return `tradegraph.uncertain-cancel.v1.${opaque}.${id}`;
  };
  return {
    async pending(scope: string, id: string) {
      return !!storage.getItem(await name(scope, id));
    },
    async cancel<T>(scope: string, id: string, send: () => Promise<T>) {
      const key = await name(scope, id);
      if (storage.getItem(key)) throw new ApiError(409, 'CANCEL_RECONCILIATION_REQUIRED', true);
      storage.setItem(key, JSON.stringify({ submittedAt: Date.now(), state: 'SUBMITTING' }));
      try {
        const result = await send();
        storage.removeItem(key);
        return result;
      } catch (e) {
        if (e instanceof ApiError && !e.uncertain) storage.removeItem(key);
        else storage.setItem(key, JSON.stringify({ submittedAt: Date.now(), state: 'UNCERTAIN' }));
        throw e;
      }
    },
    async reconcile<T extends { id: string; trader_id: string; status: string }>(
      scope: string,
      id: string,
      lookup: () => Promise<T>,
    ) {
      const key = await name(scope, id);
      const row = await lookup();
      if (
        row.id !== id ||
        row.trader_id !== scope ||
        !['OPEN', 'PARTIAL', 'FILLED', 'CANCELLED'].includes(row.status)
      )
        throw new ApiError(409, 'CANCEL_RECONCILIATION_REQUIRED', true);
      storage.removeItem(key);
      return row;
    },
  };
}
