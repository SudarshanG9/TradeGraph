import { ApiError } from '../api/errors';
/** Trusted server configuration shared by cookies and CSRF; never use Host headers. */
export function applicationOrigin(env: Record<string, string | undefined> = process.env) {
  const production = env.NODE_ENV === 'production';
  const value = env.APP_ORIGIN ?? (production ? '' : 'http://127.0.0.1:3000');
  try {
    if (!value || value.trim() !== value || /[?#]/.test(value)) throw new Error();
    const url = new URL(value);
    const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
    if (
      url.username ||
      url.password ||
      url.pathname !== '/' ||
      !['http:', 'https:'].includes(url.protocol)
    )
      throw new Error();
    if (
      url.protocol !== 'https:' &&
      (!loopback || (production && env.ALLOW_INSECURE_LOOPBACK_ORIGIN !== 'true'))
    )
      throw new Error();
    return url.origin;
  } catch {
    throw new ApiError(503, 'APP_ORIGIN_CONFIGURATION_INVALID');
  }
}
