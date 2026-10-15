/**
 * Storm Energy RTU — the ONE place the frontend talks to the backend.
 *
 * - Same-origin relative paths only ('/api/...', '/health'). In production the reverse
 *   proxy routes them to storm-api; there is no host, port or environment-specific URL.
 * - NO mock data and NO fallback: a failed request throws an ApiError and the page shows
 *   its error state. Nothing is ever substituted for a failed response.
 * - Read-only: only GET is exposed. Write endpoints exist in the API but are deliberately
 *   not callable from this UI until authentication is enabled.
 * - Retries only on network errors / timeouts (never on HTTP 4xx/5xx responses).
 */

export class ApiError extends Error {
  constructor(message, { status = null, path = '', cause = null } = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.path = path;
    this.cause = cause;
  }
}

const DEFAULT_TIMEOUT_MS = 20_000;
const NETWORK_RETRIES = 1;

function buildUrl(path, params) {
  if (!path.startsWith('/api/') && path !== '/health' && !path.startsWith('/health/')) {
    throw new ApiError(`Refusing non-API path: ${path}`, { path });
  }
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params || {})) {
    if (v !== undefined && v !== null && v !== '') qs.append(k, String(v));
  }
  const q = qs.toString();
  return q ? `${path}?${q}` : path;
}

async function detailFrom(res) {
  try {
    const body = await res.json();
    if (body && typeof body.detail === 'string') return body.detail;
  } catch {
    /* non-JSON error body */
  }
  return res.statusText || 'Request failed';
}

/**
 * GET JSON. `signal` aborts the request (component unmount / refresh); an aborted
 * request rejects with the AbortError so callers can ignore it.
 */
export async function apiGet(path, { params, signal, timeoutMs = DEFAULT_TIMEOUT_MS } = {}) {
  const url = buildUrl(path, params);
  let lastErr = null;
  for (let attempt = 0; attempt <= NETWORK_RETRIES; attempt += 1) {
    const controller = new AbortController();
    const onAbort = () => controller.abort();
    if (signal) {
      if (signal.aborted) throw new DOMException('Aborted', 'AbortError');
      signal.addEventListener('abort', onAbort, { once: true });
    }
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const res = await fetch(url, {
        method: 'GET',
        headers: { Accept: 'application/json' },
        cache: 'no-store',
        credentials: 'same-origin',
        signal: controller.signal,
      });
      if (!res.ok) {
        throw new ApiError(`${await detailFrom(res)} (HTTP ${res.status})`, { status: res.status, path });
      }
      try {
        return await res.json();
      } catch (e) {
        throw new ApiError('The server returned an invalid response', { status: res.status, path, cause: e });
      }
    } catch (err) {
      if (signal?.aborted) throw new DOMException('Aborted', 'AbortError');
      if (err instanceof ApiError) throw err;            // HTTP errors are final, never retried
      lastErr = new ApiError(
        controller.signal.aborted ? 'The server did not respond in time' : 'Cannot reach the Storm RTU server',
        { path, cause: err },
      );
    } finally {
      clearTimeout(timer);
      if (signal) signal.removeEventListener('abort', onAbort);
    }
  }
  throw lastErr;
}

export function isAbort(err) {
  return err?.name === 'AbortError';
}
