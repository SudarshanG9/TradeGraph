import 'server-only';
import type { Operation } from '../api/operations';
import { backendRequest } from './transport-core';
export function requestBackend(op: Operation, token?: string, signal?: AbortSignal) {
  return backendRequest(op, token, {
    baseUrl: process.env.FASTAPI_BASE_URL ?? 'http://127.0.0.1:8000',
    signal,
    timeoutMs: op.kind === 'optimizer' ? 35000 : 15000,
  });
}
