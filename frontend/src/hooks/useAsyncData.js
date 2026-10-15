/**
 * useAsyncData(loader, deps, { enabled, keepPrevious }) — runs `loader(signal)` whenever the
 * (primitive) deps change or reload() is called. In-flight requests are aborted on change or
 * unmount. Errors are surfaced as-is; there is never fallback data.
 *
 * Returns { data, error, loading, reload }.
 *  - keepPrevious=false (default): data/error are null while a new request is loading, so a
 *    page can never show one device's data under another device's heading.
 *  - keepPrevious=true: the last successful data stays visible while refreshing (used for
 *    periodically re-anchored windows, to avoid a skeleton flash on every poll).
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { isAbort } from '../services/apiClient';

export function useAsyncData(loader, deps, { enabled = true, keepPrevious = false } = {}) {
  const [tick, setTick] = useState(0);
  const key = JSON.stringify([...deps, tick]);
  const [result, setResult] = useState({ key: null, data: null, error: null });
  const loaderRef = useRef(loader);

  useEffect(() => {
    loaderRef.current = loader;
  });

  useEffect(() => {
    if (!enabled) return undefined;
    const ctrl = new AbortController();
    Promise.resolve()
      .then(() => loaderRef.current(ctrl.signal))
      .then((data) => { if (!ctrl.signal.aborted) setResult({ key, data, error: null }); })
      .catch((error) => {
        if (isAbort(error) || ctrl.signal.aborted) return;
        setResult((prev) => ({ key, data: keepPrevious ? prev.data : null, error }));
      });
    return () => ctrl.abort();
  }, [key, enabled, keepPrevious]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const current = result.key === key;
  if (!enabled) return { data: null, error: null, loading: false, reload };
  return {
    data: current || keepPrevious ? result.data : null,
    error: current ? result.error : null,
    loading: !current,
    reload,
  };
}
