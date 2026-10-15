/**
 * Protocol Test Log — READ-ONLY diagnostic viewer for what actually arrives at the Storm
 * TCP listener and MQTT consumer (valid, invalid and unknown-device traffic).
 *
 * - Data: GET /api/diagnostics/{tcp|mqtt} (server-side pagination, newest first) and
 *   GET /api/diagnostics/{tcp|mqtt}/{id} for the complete payload of one record.
 * - Every timestamp is the SERVER receipt time, displayed exactly as the server formatted
 *   it. The SERVER TIME clock is derived from the server's time (never the browser clock).
 * - Payloads are rendered as React text nodes only (never as HTML), so a payload such as
 *   "<script>" is shown, not executed.
 * - Auto-refresh every 5 s: the next request is scheduled only after the previous one has
 *   finished, and polling pauses while the browser tab is hidden.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { DIAG_PAGE_SIZES, fetchDiagnostic, fetchDiagnostics } from '../services/stormApi';
import { isAbort } from '../services/apiClient';
import { formatIstMs, makeAnchor, serverNowFromAnchor } from '../utils/serverClock';
import './TestLogsPage.css';

export const REFRESH_MS = 5000;
const mono = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());

const TABS = {
  tcp: {
    label: 'TCP',
    title: 'TCP TEST LOG',
    filters: [
      { key: 'device_id', label: 'Device', placeholder: 'device ID or name' },
      { key: 'imei', label: 'IMEI', placeholder: 'IMEI' },
      { key: 'source_ip', label: 'Source IP', placeholder: 'e.g. 192.168.0.' },
    ],
  },
  mqtt: {
    label: 'MQTT',
    title: 'MQTT TEST LOG',
    filters: [
      { key: 'device_id', label: 'Device ID', placeholder: 'device ID or name' },
      { key: 'topic', label: 'Topic', placeholder: 'storm/meters/…' },
    ],
  },
};

const STATUS_TEXT = { VALID: 'VALID', INVALID: 'INVALID', UNKNOWN_DEVICE: 'UNKNOWN DEVICE' };
const STATUS_CLASS = { VALID: 'ok', INVALID: 'bad', UNKNOWN_DEVICE: 'warn' };

export function DiagStatus({ status }) {
  return <span className={`tlog-badge ${STATUS_CLASS[status] || 'warn'}`} data-status={status}>{STATUS_TEXT[status] || status}</span>;
}

function deviceLabel(r) {
  if (r.status === 'INVALID' || !r.device_id) return 'UNKNOWN';
  return r.device_name || r.device_id;
}

function PayloadCell({ item, onOpen }) {
  return (
    <td className="tlog-payload">
      <button type="button" className="tlog-link" onClick={() => onOpen(item.id)} title="Show complete payload">
        {item.payload_encoding === 'HEX' && <span className="tlog-tag">HEX</span>}
        {item.payload_preview || '(empty)'}
      </button>
    </td>
  );
}

function DetailDialog({ protocol, id, onClose }) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  useEffect(() => {
    const ctrl = new AbortController();
    fetchDiagnostic(protocol, id, ctrl.signal)
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((error) => { if (!isAbort(error)) setState({ loading: false, data: null, error }); });
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => { ctrl.abort(); document.removeEventListener('keydown', onKey); };
  }, [protocol, id, onClose]);

  const d = state.data;
  return (
    <div className="tlog-modal-backdrop" onClick={onClose}>
      <div className="tlog-modal" role="dialog" aria-modal="true" aria-label="Diagnostic record" onClick={(e) => e.stopPropagation()}
        data-testid="tlog-detail">
        <div className="tlog-modal-head">
          <span>{protocol.toUpperCase()} RECORD #{id}</span>
          <button type="button" className="tlog-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>
        {state.loading && <div className="tlog-muted">Loading…</div>}
        {state.error && <div className="tlog-error">{state.error.message}</div>}
        {d && (
          <>
            <div className="tlog-kv">
              <div>Received (server)</div><div>{d.received_at_display}</div>
              <div>Status</div><div><DiagStatus status={d.status} /> {d.outcome ? <span className="tlog-muted">{d.outcome}</span> : null}</div>
              <div>Device</div><div>{deviceLabel(d)}{d.device_id && d.device_name ? ` (${d.device_id})` : ''}{d.status === 'UNKNOWN_DEVICE' ? ' — not registered' : ''}</div>
              <div>IMEI</div><div>{d.imei || '—'}</div>
              <div>Site ID</div><div>{d.site_id || '—'}</div>
              {protocol === 'tcp' ? (<><div>Source IP</div><div>{d.source_ip || '—'}</div></>)
                : (<><div>Topic</div><div>{d.topic || '—'}</div><div>QoS</div><div>{d.qos ?? '—'}</div></>)}
              <div>Payload</div><div>{d.payload_bytes} bytes · {d.payload_encoding === 'HEX' ? 'binary shown as hex' : 'text'}{d.payload_truncated ? ' · truncated to the stored maximum' : ''}</div>
              {d.error_reason && (<><div>Error</div><div className="tlog-error">{d.error_reason}</div></>)}
            </div>
            <div className="tlog-sec">PAYLOAD (stored, shown as text)</div>
            <pre className="tlog-pre" data-testid="tlog-payload-full">{d.payload}</pre>
          </>
        )}
      </div>
    </div>
  );
}

export default function TestLogsPage() {
  const [params, setParams] = useSearchParams();
  const protocol = params.get('tab') === 'mqtt' ? 'mqtt' : 'tcp';
  const tab = TABS[protocol];

  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [status, setStatus] = useState('');
  const [draft, setDraft] = useState({});        // filter inputs being typed
  const [filters, setFilters] = useState({});    // applied filters
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);           // manual refresh trigger
  const [anchor, setAnchor] = useState(null);    // server clock anchor
  const [clock, setClock] = useState(null);
  const [openId, setOpenId] = useState(null);
  const timer = useRef(null);

  const switchTab = (p) => {
    setParams(p === 'tcp' ? {} : { tab: p });
    setPage(1); setStatus(''); setDraft({}); setFilters({}); setData(null); setLoading(true);
  };

  // Fetch the requested page; schedule the next poll only after this one completes.
  useEffect(() => {
    const ctrl = new AbortController();
    let cancelled = false;
    const load = async () => {
      if (typeof document !== 'undefined' && document.hidden) {
        timer.current = setTimeout(load, REFRESH_MS);
        return;
      }
      try {
        const res = await fetchDiagnostics(protocol, {
          page, pageSize, filters: { ...filters, status: status || undefined },
        }, ctrl.signal);
        if (cancelled) return;
        setData(res); setError(null); setAnchor(makeAnchor(res.server_time, mono()));
      } catch (err) {
        if (cancelled || isAbort(err)) return;
        setError(err);
      } finally {
        if (!cancelled) {
          setLoading(false);
          timer.current = setTimeout(load, REFRESH_MS);
        }
      }
    };
    load();
    return () => { cancelled = true; ctrl.abort(); clearTimeout(timer.current); };
  }, [protocol, page, pageSize, status, filters, tick]);

  // SERVER TIME display: server anchor advanced by a monotonic clock (not Date.now()).
  useEffect(() => {
    if (!anchor) return undefined;
    const update = () => setClock(serverNowFromAnchor(anchor, mono()));
    const first = setTimeout(update, 0);
    const id = setInterval(update, 1000);
    return () => { clearTimeout(first); clearInterval(id); };
  }, [anchor]);

  const applyFilters = (e) => {
    e.preventDefault();
    const clean = {};
    for (const f of tab.filters) { const v = (draft[f.key] || '').trim(); if (v) clean[f.key] = v; }
    setFilters(clean); setPage(1);
  };
  const clearFilters = () => { setDraft({}); setFilters({}); setStatus(''); setPage(1); };
  const closeDetail = useCallback(() => setOpenId(null), []);

  const items = data?.items ?? [];
  const totalPages = data?.total_pages ?? 1;
  const cols = protocol === 'tcp'
    ? ['Received Time', 'Device', 'IMEI', 'Site ID', 'Source IP', 'Protocol', 'Status', 'Payload']
    : ['Received Time', 'Device', 'Device ID', 'Topic', 'Source', 'Protocol', 'Status', 'Payload'];

  return (
    <div className="tlog" data-testid="page-test-logs">
      <header className="tlog-head">
        <h1>STORM ENERGY RTU — {tab.title}</h1>
        <div className="tlog-sub">Read-only viewer · newest first · shows valid, invalid and unknown-device traffic · internal testing only</div>
        <div className="tlog-tabs" role="tablist">
          {Object.entries(TABS).map(([k, t]) => (
            <button key={k} type="button" role="tab" aria-selected={protocol === k}
              className={`tlog-tab${protocol === k ? ' active' : ''}`} onClick={() => switchTab(k)}>
              [ {t.label} ]
            </button>
          ))}
        </div>
      </header>

      <div className="tlog-status" data-testid="tlog-status">
        <div><span className={`tlog-dot ${error ? 'bad' : 'ok'}`} />SERVER TIME <b data-testid="tlog-server-time">{clock != null ? formatIstMs(clock) : (data?.server_time_display || '—')}</b></div>
        <div>LAST {tab.label} MESSAGE <b data-testid="tlog-last">{data ? (data.latest_received_at_display || 'none received yet') : '—'}</b></div>
        <div>RECORDS <b data-testid="tlog-total">{data ? data.total.toLocaleString('en-IN') : '—'}</b>{data ? <span className="tlog-muted"> (kept {data.retention_days} days)</span> : null}</div>
        <div>AUTO REFRESH: <b>{REFRESH_MS / 1000}s</b></div>
        <button type="button" className="tlog-btn" onClick={() => setTick((t) => t + 1)}>REFRESH</button>
      </div>

      <form className="tlog-filters" onSubmit={applyFilters}>
        <label>Status
          <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} aria-label="Status filter">
            <option value="">All</option>
            <option value="VALID">VALID</option>
            <option value="INVALID">INVALID</option>
            <option value="UNKNOWN_DEVICE">UNKNOWN DEVICE</option>
          </select>
        </label>
        {tab.filters.map((f) => (
          <label key={f.key}>{f.label}
            <input value={draft[f.key] || ''} placeholder={f.placeholder} maxLength={f.key === 'topic' ? 255 : 50}
              aria-label={`${f.label} filter`} onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))} />
          </label>
        ))}
        <button type="submit" className="tlog-btn">APPLY</button>
        <button type="button" className="tlog-btn" onClick={clearFilters}>CLEAR</button>
      </form>

      {error && <div className="tlog-error tlog-banner">Cannot load the {tab.label} test log: {error.message}{data ? ' — showing the last successful page.' : ''}</div>}

      <div className="tlog-table-wrap">
        <table className="tlog-table" data-testid="tlog-table">
          <thead><tr>{cols.map((c) => <th key={c}>{c}</th>)}</tr></thead>
          <tbody>
            {loading && !data && <tr><td colSpan={cols.length} className="tlog-muted">Loading…</td></tr>}
            {data && items.length === 0 && (
              <tr><td colSpan={cols.length} className="tlog-muted">
                {Object.keys(filters).length || status ? 'No records match the filters.' : `No ${tab.label} messages received yet.`}
              </td></tr>
            )}
            {items.map((r) => (
              <tr key={r.id} className={`row ${STATUS_CLASS[r.status] || ''}`}>
                <td className="tlog-nowrap">{r.received_at_display}</td>
                <td className="tlog-nowrap">{deviceLabel(r)}</td>
                {protocol === 'tcp' ? (
                  <>
                    <td className="tlog-nowrap">{r.imei || '—'}</td>
                    <td className="tlog-nowrap">{r.status === 'INVALID' ? '—' : (r.site_id || '—')}</td>
                    <td className="tlog-nowrap">{r.source_ip || '—'}</td>
                  </>
                ) : (
                  <>
                    <td>{r.status === 'INVALID' ? '—' : (r.device_id || '—')}</td>
                    <td className="tlog-topic">{r.topic || '—'}</td>
                    <td className="tlog-muted" title="The MQTT broker does not pass the publisher's IP or client ID to subscribers">
                      {r.source_ip || 'broker (not exposed)'}
                    </td>
                  </>
                )}
                <td>{protocol === 'tcp' ? 'TCP' : `MQTT${r.qos != null ? ` · QoS ${r.qos}` : ''}`}</td>
                <td><DiagStatus status={r.status} />{r.error_reason ? <div className="tlog-reason" title={r.error_reason}>{r.error_reason}</div> : null}</td>
                <PayloadCell item={r} onOpen={setOpenId} />
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="tlog-foot">
        <button type="button" className="tlog-btn" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>◀ PREV</button>
        <span data-testid="tlog-page">Page {data ? data.page : page} of {totalPages}</span>
        <button type="button" className="tlog-btn" disabled={!data || page >= totalPages} onClick={() => setPage((p) => p + 1)}>NEXT ▶</button>
        <label>Rows
          <select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }} aria-label="Rows per page">
            {DIAG_PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <span className="tlog-muted">Times are server receipt times (IST). Records older than {data?.retention_days ?? 30} days are removed automatically.</span>
      </div>

      {openId != null && <DetailDialog protocol={protocol} id={openId} onClose={closeDetail} />}
    </div>
  );
}
