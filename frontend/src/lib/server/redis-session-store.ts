import { randomBytes, createCipheriv, createDecipheriv } from 'node:crypto';
import Redis from 'ioredis';
import type { ServerSession, SessionStore } from './session-core';
import { ApiError } from '../api/errors';

const namespace = 'tradegraph:frontend:session:';
/** Shared encrypted session data; a Redis error never falls back to local memory. */
export class RedisSessionStore implements SessionStore {
  private connecting?: Promise<void>;
  private async ready() {
    if (this.client.status === 'ready') return;
    if (this.client.status === 'wait' && !this.connecting)
      this.connecting = this.client
        .connect()
        .then(() => {})
        .finally(() => {
          this.connecting = undefined;
        });
    if (this.connecting) await this.connecting;
    if (String(this.client.status) !== 'ready') throw new ApiError(503, 'SESSION_UNAVAILABLE');
  }
  constructor(
    private client: Redis,
    private key: Buffer,
  ) {
    if (key.length !== 32) throw new ApiError(503, 'SESSION_CONFIGURATION_INVALID');
  }
  async create(session: ServerSession) {
    await this.ready();
    const id = randomBytes(32).toString('base64url');
    const iv = randomBytes(12);
    const cipher = createCipheriv('aes-256-gcm', this.key, iv);
    cipher.setAAD(Buffer.from(namespace + id));
    const encrypted = Buffer.concat([cipher.update(JSON.stringify(session)), cipher.final()]);
    const value = [iv, cipher.getAuthTag(), encrypted]
      .map((b) => b.toString('base64url'))
      .join('.');
    const ttl = session.expiresAt - Date.now();
    if (ttl <= 0) throw new ApiError(401, 'UNAUTHORIZED');
    const result = await this.client.set(namespace + id, value, 'PX', Math.floor(ttl), 'NX');
    if (result !== 'OK') throw new ApiError(503, 'SESSION_UNAVAILABLE');
    return id;
  }
  async get(id: string): Promise<ServerSession | null> {
    await this.ready();
    const value = await this.client.get(namespace + id);
    if (!value) return null;
    try {
      const [iv, tag, encrypted] = value.split('.').map((s) => Buffer.from(s, 'base64url'));
      const decipher = createDecipheriv('aes-256-gcm', this.key, iv);
      decipher.setAAD(Buffer.from(namespace + id));
      decipher.setAuthTag(tag);
      return JSON.parse(Buffer.concat([decipher.update(encrypted), decipher.final()]).toString());
    } catch {
      throw new ApiError(503, 'SESSION_UNAVAILABLE');
    }
  }
  async delete(id: string) {
    await this.ready();
    await this.client.del(namespace + id);
  }
}

let store: SessionStore | undefined;
export function sharedSessionStore(): SessionStore {
  if (store) return store;
  const secret = process.env.SESSION_ENCRYPTION_KEY;
  if (!secret || !/^[0-9a-f]{64}$/i.test(secret))
    throw new ApiError(503, 'SESSION_CONFIGURATION_INVALID');
  const url = process.env.REDIS_URL;
  if (!url || !['redis:', 'rediss:'].includes(new URL(url).protocol))
    throw new ApiError(503, 'SESSION_CONFIGURATION_INVALID');
  const client = new Redis(url, {
    lazyConnect: true,
    connectTimeout: 2000,
    commandTimeout: 2500,
    maxRetriesPerRequest: 1,
    enableOfflineQueue: false,
    retryStrategy: (attempt) => Math.min(attempt * 100, 2000),
  });
  // No tokens, URL credentials or raw connection errors enter logs.
  client.on('error', () => {});
  store = new RedisSessionStore(client, Buffer.from(secret, 'hex'));
  return store;
}
