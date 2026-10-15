/**
 * StormDataContext — the shared, polled snapshot of the meter registry.
 *
 * One request (GET /api/devices/latest) feeds the hero KPIs, the Overview table, the GIS
 * map. It is refreshed every `refreshMs` (default 60 s)
 * and on demand. On failure the previous snapshot is KEPT and flagged stale together with
 * the error — nothing is ever replaced by mock/demo data.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { fetchDevicesLatest } from '../services/stormApi';
import { isAbort } from '../services/apiClient';
import { computeKpis } from '../utils/meterStatus';
import { getPref } from '../utils/prefs';

const StormDataContext = createContext(null);

export function StormDataProvider({ children, refreshMs }) {
  const interval = refreshMs ?? getPref('refreshSeconds') * 1000;
  const [snapshot, setSnapshot] = useState(null);     // { server_time, devices }
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);       // true until the first response (ok or error)
  const [refreshing, setRefreshing] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const ctrlRef = useRef(null);

  const refresh = useCallback(async () => {
    ctrlRef.current?.abort();
    const ctrl = new AbortController();
    ctrlRef.current = ctrl;
    setRefreshing(true);
    try {
      const data = await fetchDevicesLatest(ctrl.signal);
      if (!data || !Array.isArray(data.devices)) throw new Error('Unexpected response from /api/devices/latest');
      setSnapshot(data);
      setError(null);
      setLastUpdated(new Date());
    } catch (err) {
      if (isAbort(err)) return;
      setError(err);
    } finally {
      if (ctrlRef.current === ctrl) {
        setRefreshing(false);
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    const first = setTimeout(refresh, 0);   // initial load, then poll
    const id = interval > 0 ? setInterval(refresh, interval) : null;
    return () => {
      clearTimeout(first);
      if (id) clearInterval(id);
      ctrlRef.current?.abort();
    };
  }, [refresh, interval]);

  const value = useMemo(() => {
    const devices = snapshot?.devices ?? [];
    const serverTime = snapshot?.server_time ?? null;
    return {
      devices,
      serverTime,
      kpis: snapshot ? computeKpis(devices, serverTime) : null,
      hasData: snapshot != null,
      loading,
      refreshing,
      error,
      lastUpdated,
      refresh,
    };
  }, [snapshot, loading, refreshing, error, lastUpdated, refresh]);

  return <StormDataContext.Provider value={value}>{children}</StormDataContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useStormData() {
  const ctx = useContext(StormDataContext);
  if (!ctx) throw new Error('useStormData must be used inside <StormDataProvider>');
  return ctx;
}
