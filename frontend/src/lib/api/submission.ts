import { ApiError } from './errors';
/** Persist uncertain intent across navigation/reload. No automatic retry or new key. */
export function createSubmissionGate(
  storage?: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>,
) {
  const name = 'tradegraph.uncertain-order.v1';
  let pending = false;
  const blocked = () => pending || !!storage?.getItem(name);
  return async <T>(send: (key: string) => Promise<T>): Promise<T> => {
    if (blocked()) throw new ApiError(409, 'ORDER_RECONCILIATION_REQUIRED', true);
    const key = crypto.randomUUID();
    pending = true;
    // Write before dispatch: a reload during the request is also uncertain.
    storage?.setItem(name, key);
    try {
      const result = await send(key);
      storage?.removeItem(name);
      return result;
    } catch (e) {
      if (e instanceof ApiError && !e.uncertain && e.code !== 'DUPLICATE_REQUEST')
        storage?.removeItem(name);
      throw e;
    } finally {
      pending = false;
    }
  };
}
