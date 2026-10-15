/**
 * Testing / Protocol Monitor — shows EVERYTHING that arrives at the server (valid, unknown
 * device, invalid, malformed; TCP and MQTT), for engineers testing RTUs. READ-ONLY.
 *
 * Data (all derived from ProtocolDiagnosticLogs, the source of truth):
 *   GET /api/diagnostics/summary        status bar (server time, services, counts)
 *   GET /api/diagnostics/sources        every device / source seen in the window
 *   GET /api/diagnostics/packets        live packet stream (paged, filtered, newest first)
 *   GET /api/diagnostics/packets/{id}   packet detail: parsed, raw, escaped, hex, errors
 *
 * - Timestamps are SERVER receipt times, shown as the server formatted them; the SERVER TIME
 *   clock is advanced from the server's time with a monotonic clock (never Date.now()).
 * - Payloads are rendered only as React text (never as HTML).
 * - Polling (no websocket): the next request starts only after the previous one finished,
 *   and polling pauses while the tab is hidden. The API is page-based so SSE/websocket
 *   push can be added later without changing the data model.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  DIAG_PAGE_SIZES, fetchPacket, fetchPackets, fetchTestingSources, fetchTestingSummary,
} from '../services/stormApi';
import { isAbort } from '../services/apiClient';
import { formatIstMs, makeAnchor, serverNowFromAnchor } from '../utils/serverClock';
import { fmtNum, meterStatus, parseApiTimestamp } from '../utils/meterStatus';
import { DEFAULT_REFRESH_S, REFRESH_CHOICES, TELEMETRY_ROWS } from '../utils/testingModel';
import './Testing.css';

const SOURCES_MIN_MS = 30000;      // the per-source aggregation is heavier: at most every 30 s
const mono = () => (typeof performance !== 'undefined' ? performance.now() : Date.now());

const STATUS_TEXT = { VALID: 'VALID', INVALID: 'INVALID', UNKNOWN_DEVICE: 'UNKNOWN' };
const STATUS_CLASS = { VALID: 'ok', INVALID: 'bad', UNKNOWN_DEVICE: 'warn' };
const TABS = [{ key: 'TCP', label: 'TCP' }, { key: 'MQTT', label: 'MQTT' }, { key: 'ALL', label: 'Packets' }];

/** Badge label: INVALID packets the parser could not parse at all are shown as PARSE ERROR. */
function badgeFor(status, outcome) {
  if (status === 'INVALID' && outcome === 'PARSE_ERROR') return { text: 'PARSE ERROR', cls: 'err' };
  return { text: STATUS_TEXT[status] || status, cls: STATUS_CLASS[status] || 'warn' };
}
const WINDOWS = [
  { key: 'today', label: 'Today' }, { key: '1h', label: 'Last 1 hour' },
  { key: '24h', label: 'Last 24 hours' }, { key: 'custom', label: 'Custom' },
];

export function PacketStatus({ status, outcome }) {
  const b = badgeFor(status, outcome);
  return <span className={`tlog-badge ${b.cls}`} data-status={status}>{b.text}</span>;
}

export function ProtoBadge({ protocol, label }) {
  return <span className={`tst-pill ${String(protocol).toLowerCase()}`}>{label || protocol}</span>;
}

/** NULL / missing stays visibly N/A — never converted to 0. */
export function NA({ value }) {
  if (value === null || value === undefined || value === '') return <span className="tst-na">N/A</span>;
  return <>{String(value)}</>;
}

function svcClass(s) {
  if (!s) return 'muted';
  if (s.status === 'ok') return 'ok';
  if (s.status === 'down') return 'bad';
  return 'muted';
}

function sourceStatus(src, nowMs) {
  if (!src.is_registered) return 'unknown';
  return meterStatus({ is_active: src.device_is_active, last_seen_at: src.device_last_seen_at }, nowMs);
}

const dash = (v) => (v === null || v === undefined || v === '' ? '—' : v);

function PacketDetail({ id, onClose }) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  useEffect(() => {
    const ctrl = new AbortController();
    fetchPacket(id, ctrl.signal)
      .then((data) => setState({ loading: false, data, error: null }))
      .catch((error) => { if (!isAbort(error)) setState({ loading: false, data: null, error }); });
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => { ctrl.abort(); document.removeEventListener('keydown', onKey); };
  }, [id, onClose]);
  const d = state.data;
  const fc = d?.field_check;

  return (
    <div className="tst-detail-wrap">
      <aside className="tst-detail" role="region" aria-label="Selected packet details" data-testid="packet-detail">
        <div className="tlog-modal-head">
          <span>SELECTED PACKET #{id}{d ? ` · ${d.protocol_label}` : ''}</span>
          <button type="button" className="tlog-btn" onClick={onClose} aria-label="Close">✕</button>
        </div>
        {state.loading && <div className="tlog-muted">Loading…</div>}
        {state.error && <div className="tst-errbox">{state.error.message}</div>}
        {d && (
          <>
            <div className="tst-kv" data-testid="packet-meta">
              <div>Received time</div><div>{d.received_at_display}</div>
              <div>Server time</div><div>{d.server_time_display}</div>
              <div>Source IP</div><div>{d.protocol === 'TCP' ? dash(d.source_ip) : 'broker (publisher IP not exposed by MQTT)'}</div>
              {d.protocol === 'MQTT' && (<><div>Topic</div><div>{dash(d.topic)}</div></>)}
              <div>Device ID</div><div>{d.status === 'INVALID' ? 'UNKNOWN' : dash(d.device_id)}{d.device_name ? ` (${d.device_name})` : ''}</div>
              <div>IMEI</div><div>{dash(d.imei)}</div>
              <div>Site ID</div><div>{d.status === 'INVALID' ? '—' : dash(d.site_id)}</div>
              <div>Protocol</div><div>{d.protocol_label}</div>
              <div>Status</div><div><PacketStatus status={d.status} outcome={d.outcome} /> {d.is_registered ? 'registered device' : (d.status === 'UNKNOWN_DEVICE' ? 'not registered' : '')}</div>
              <div>{d.protocol === 'TCP' ? 'TCP received' : 'MQTT received'}</div><div>{d.transport_received}</div>
              <div>Parse status</div><div>{d.parse_status}</div>
              <div>Database status</div><div>{d.database_status}</div>
              <div>Acknowledgement</div><div>{d.acknowledgement}</div>
              <div>Raw message ID</div><div><NA value={d.raw_message_id} /></div>
              <div>Payload size</div><div>{d.size} bytes · {d.payload_format}{d.payload_complete ? '' : ' · TRUNCATED in storage'}</div>
            </div>

            <div className="tst-h">1. PARSED TELEMETRY</div>
            {d.telemetry ? (
              <div className="tst-kv" data-testid="parsed-telemetry">
                {TELEMETRY_ROWS.map(([k, label]) => (
                  <FragmentRow key={k} label={label} value={d.telemetry[k]} />
                ))}
              </div>
            ) : (
              <div className="tlog-muted" data-testid="parsed-telemetry-none">
                Not parsed{d.reparse_error ? ` — ${d.reparse_error}` : (d.status === 'INVALID' ? ' — the parser rejected this payload' : ' — not a telemetry message')}.
              </div>
            )}

            {fc && (
              <>
                <div className="tst-h">PROTOCOL FIELD CHECK (MQTT JSON, Scanvix V1.3)</div>
                <table className="tst-check" data-testid="field-check">
                  <tbody>
                    {fc.fields.map((f) => (
                      <tr key={f.field}>
                        <td>{f.field}{f.required ? ' *' : ''}</td>
                        <td>{!f.present ? <span className={f.required ? 'tlog-error' : 'tst-na'}>absent</span> : f.is_null ? <span className="tst-na">null</span> : 'present'}</td>
                        <td>{f.present && f.key !== f.field ? `as "${f.key}"` : ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div className="tlog-muted">* required by the server parser; all other fields are optional and may be null.</div>
                {fc.missing_required.length > 0 && <div className="tst-errbox">Missing required: {fc.missing_required.join(', ')}</div>}
                {fc.duplicate_keys.length > 0 && (
                  <div className="tst-warnbox" data-testid="duplicate-keys">
                    Duplicate key(s) in payload: {fc.duplicate_keys.join(', ')} — the last value is used for the single
                    canonical field; the raw payload below is kept unchanged.
                  </div>
                )}
                {fc.undocumented_keys.length > 0 && <div className="tlog-muted">Undocumented keys (ignored): {fc.undocumented_keys.join(', ')}</div>}
              </>
            )}

            <div className="tst-h">2. RAW PAYLOAD</div>
            {d.payload_text !== null
              ? <pre className="tlog-pre" data-testid="raw-payload">{d.payload_text}</pre>
              : <div className="tlog-muted" data-testid="raw-payload">Binary / non-printable payload — see the escaped and HEX views.</div>}

            <div className="tst-h">3. SAFE ESCAPED PAYLOAD</div>
            <pre className="tlog-pre" data-testid="escaped-payload">{d.payload_escaped}</pre>

            <div className="tst-h">4. RAW HEX ({d.size} bytes{d.payload_complete ? '' : ', stored part only'})</div>
            <pre className="tlog-pre" data-testid="hex-payload">{d.payload_hex || '(empty)'}</pre>

            <div className="tst-h">5. ERROR MESSAGE</div>
            {d.error_reason || d.reparse_error
              ? <div className="tst-errbox" data-testid="error-message">{d.error_reason || d.reparse_error}</div>
              : <div className="tlog-muted">None.</div>}
          </>
        )}
      </aside>
    </div>
  );
}

function FragmentRow({ label, value }) {
  return (<><div>{label}</div><div><NA value={value} /></div></>);
}

export default function TestingPage() {
  const [params] = useSearchParams();
  const initialProtocol = ['TCP', 'MQTT'].includes((params.get('protocol') || '').toUpperCase())
    ? params.get('protocol').toUpperCase() : 'ALL';
  const initialDevice = params.get('device') || '';

  const [filters, setFilters] = useState({ protocol: initialProtocol, status: '', device_id: initialDevice, site_id: '', source_ip: '', topic: '' });
  const [draft, setDraft] = useState({ device_id: initialDevice, site_id: '', source_ip: '', topic: '' });
  const [windowKey, setWindowKey] = useState('24h');
  const [custom, setCustom] = useState({ from: '', to: '' });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [auto, setAuto] = useState(true);
  const [intervalS, setIntervalS] = useState(DEFAULT_REFRESH_S);
  const [tick, setTick] = useState(0);
  const [summary, setSummary] = useState(null);
  const [sources, setSources] = useState(null);
  const [packets, setPackets] = useState(null);
  const [error, setError] = useState(null);
  const [anchor, setAnchor] = useState(null);
  const [clock, setClock] = useState(null);
  const [openId, setOpenId] = useState(null);
  const lastSources = useRef(0);
  const timer = useRef(null);

  const query = useMemo(() => {
    const q = { window: windowKey };
    if (filters.protocol !== 'ALL') q.protocol = filters.protocol;
    for (const k of ['status', 'device_id', 'site_id', 'source_ip', 'topic']) if (filters[k]) q[k] = filters[k];
    if (windowKey === 'custom') {
      if (custom.from) q.from = `${custom.from}:00`;
      if (custom.to) q.to = `${custom.to}:59`;
    }
    return q;
  }, [filters, windowKey, custom]);

  useEffect(() => {
    const ctrl = new AbortController();
    let cancelled = false;
    const load = async (first) => {
      if (!first && typeof document !== 'undefined' && document.hidden) {
        timer.current = setTimeout(() => load(false), intervalS * 1000);
        return;
      }
      try {
        const wantSources = first || mono() - lastSources.current >= SOURCES_MIN_MS;
        const [sum, pk, src] = await Promise.all([
          fetchTestingSummary('today', ctrl.signal),
          fetchPackets({ page, pageSize, filters: query }, ctrl.signal),
          wantSources ? fetchTestingSources(windowKey === 'custom' ? '24h' : (windowKey === 'today' ? 'today' : windowKey), ctrl.signal) : null,
        ]);
        if (cancelled) return;
        setSummary(sum); setPackets(pk); setError(null);
        setAnchor(makeAnchor(sum.server_time, mono()));
        if (src) { setSources(src); lastSources.current = mono(); }
      } catch (err) {
        if (!cancelled && !isAbort(err)) setError(err);
      } finally {
        if (!cancelled && auto) timer.current = setTimeout(() => load(false), intervalS * 1000);
      }
    };
    load(true);
    return () => { cancelled = true; ctrl.abort(); clearTimeout(timer.current); };
  }, [query, page, pageSize, auto, intervalS, tick, windowKey]);

  useEffect(() => {
    if (!anchor) return undefined;
    const update = () => setClock(serverNowFromAnchor(anchor, mono()));
    const first = setTimeout(update, 0);
    const id = setInterval(update, 1000);
    return () => { clearTimeout(first); clearInterval(id); };
  }, [anchor]);

  const serverNowMs = parseApiTimestamp(summary?.server_time);
  const closeDetail = useCallback(() => setOpenId(null), []);
  const applyText = (e) => { e.preventDefault(); setFilters((f) => ({ ...f, ...Object.fromEntries(Object.entries(draft).map(([k, v]) => [k, v.trim()])) })); setPage(1); };
  const setFilter = (k, v) => { setFilters((f) => ({ ...f, [k]: v })); setPage(1); };
  const clearAll = () => {
    setFilters({ protocol: 'ALL', status: '', device_id: '', site_id: '', source_ip: '', topic: '' });
    setDraft({ device_id: '', site_id: '', source_ip: '', topic: '' }); setWindowKey('24h'); setPage(1);
  };
  const focusSource = (s) => {
    const next = s.device_id ? { device_id: s.device_id, source_ip: '' } : { device_id: '', source_ip: s.source_ip || '' };
    setDraft((d) => ({ ...d, ...next })); setFilters((f) => ({ ...f, ...next, protocol: s.protocol })); setPage(1);
  };

  const svc = summary?.services;
  const deviceOptions = useMemo(() => [...new Set((sources?.items || []).map((s) => s.device_id).filter(Boolean))].sort(), [sources]);
  const siteOptions = useMemo(() => [...new Set((sources?.items || []).map((s) => s.site_id).filter(Boolean))].sort(), [sources]);
  const items = packets?.items ?? [];

  return (
    <div className="tlog" data-testid="page-testing">
      <header className="tlog-head">
        <h1>Testing / Protocol Diagnostics</h1>
        <div className="tlog-sub">All traffic reaching the server incl. unknown and invalid · read-only · dev / KT only</div>
        <div className="tlog-tabs" role="tablist" aria-label="Protocol">
          {TABS.map((t) => (
            <button key={t.key} type="button" role="tab" aria-selected={filters.protocol === t.key}
              className={`tlog-tab${filters.protocol === t.key ? ' active' : ''}`} onClick={() => setFilter('protocol', t.key)}>{t.label}</button>
          ))}
        </div>
      </header>

      <div className="tst-bar" data-testid="status-bar">
        <div className="tst-cell"><div className="k">Server time</div><div className="v" data-testid="server-time">{clock != null ? formatIstMs(clock) : (summary?.server_time_display || '—')}</div></div>
        <div className="tst-cell"><div className="k">TCP listener</div><div className={`v ${svcClass(svc?.tcp_listener)}`} title={svc?.tcp_listener?.details}>{(svc?.tcp_listener?.status || '—').toUpperCase()}</div></div>
        <div className="tst-cell"><div className="k">MQTT broker</div><div className={`v ${svcClass(svc?.mqtt_broker)}`} title={svc?.mqtt_broker?.details}>{(svc?.mqtt_broker?.status || '—').toUpperCase()}</div></div>
        <div className="tst-cell"><div className="k">API</div><div className={`v ${error ? 'bad' : svcClass(svc?.api)}`}>{error ? 'UNREACHABLE' : (svc?.api?.status || '—').toUpperCase()}</div></div>
        <div className="tst-cell"><div className="k">Database</div><div className={`v ${svcClass(svc?.database)}`} title={svc?.database?.details}>{(svc?.database?.status || '—').toUpperCase()}</div></div>
        <div className="tst-cell"><div className="k">Last packet</div><div className="v" data-testid="last-packet">{summary ? (summary.last_packet_at_display ? `${summary.last_packet_at_display} · ${summary.last_packet_protocol}` : 'none yet') : '—'}</div></div>
        <div className="tst-cell"><div className="k">Packets today</div><div className="v" data-testid="count-total">{summary ? summary.total : '—'}</div></div>
        <div className="tst-cell"><div className="k">Valid</div><div className="v ok" data-testid="count-valid">{summary ? summary.valid : '—'}</div></div>
        <div className="tst-cell"><div className="k">Unknown device</div><div className="v warn" data-testid="count-unknown">{summary ? summary.unknown_device : '—'}</div></div>
        <div className="tst-cell"><div className="k">Invalid</div><div className="v bad" data-testid="count-invalid">{summary ? summary.invalid : '—'}</div></div>
      </div>

      {error && <div className="tlog-error tlog-banner">Cannot load test data: {error.message}{packets ? ' — showing the last successful data.' : ''}</div>}

      <form className="tlog-filters tst-filters" onSubmit={applyText}>
        <label>Protocol
          <select value={filters.protocol} onChange={(e) => setFilter('protocol', e.target.value)} aria-label="Protocol filter">
            <option value="ALL">ALL</option><option value="TCP">TCP</option><option value="MQTT">MQTT</option>
          </select>
        </label>
        <label>Status
          <select value={filters.status} onChange={(e) => setFilter('status', e.target.value)} aria-label="Status filter">
            <option value="">ALL</option><option value="VALID">VALID</option><option value="UNKNOWN_DEVICE">UNKNOWN_DEVICE</option><option value="INVALID">INVALID</option>
          </select>
        </label>
        <label>Device
          <input list="tst-devices" value={draft.device_id} placeholder="ALL" aria-label="Device filter" maxLength={50}
            onChange={(e) => setDraft((d) => ({ ...d, device_id: e.target.value }))} />
        </label>
        <label>Site
          <input list="tst-sites" value={draft.site_id} placeholder="ALL" aria-label="Site filter" maxLength={50}
            onChange={(e) => setDraft((d) => ({ ...d, site_id: e.target.value }))} />
        </label>
        <label>Source IP
          <input value={draft.source_ip} placeholder="search" aria-label="Source IP filter" maxLength={45}
            onChange={(e) => setDraft((d) => ({ ...d, source_ip: e.target.value }))} />
        </label>
        <label>Topic
          <input value={draft.topic} placeholder="MQTT topic" aria-label="Topic filter" maxLength={255}
            onChange={(e) => setDraft((d) => ({ ...d, topic: e.target.value }))} />
        </label>
        <label>Date / time
          <select value={windowKey} onChange={(e) => { setWindowKey(e.target.value); setPage(1); }} aria-label="Time window">
            {WINDOWS.map((w) => <option key={w.key} value={w.key}>{w.label}</option>)}
          </select>
        </label>
        {windowKey === 'custom' && (
          <>
            <label>From (server time)
              <input type="datetime-local" value={custom.from} aria-label="From" onChange={(e) => { setCustom((c) => ({ ...c, from: e.target.value })); setPage(1); }} />
            </label>
            <label>To (server time)
              <input type="datetime-local" value={custom.to} aria-label="To" onChange={(e) => { setCustom((c) => ({ ...c, to: e.target.value })); setPage(1); }} />
            </label>
          </>
        )}
        <button type="submit" className="tlog-btn">APPLY</button>
        <button type="button" className="tlog-btn" onClick={clearAll}>CLEAR</button>
        <label>Auto refresh
          <select value={auto ? String(intervalS) : 'manual'} aria-label="Auto refresh"
            onChange={(e) => { if (e.target.value === 'manual') setAuto(false); else { setAuto(true); setIntervalS(Number(e.target.value)); } }}>
            {REFRESH_CHOICES.map((s) => <option key={s} value={s}>ON · {s} sec</option>)}
            <option value="manual">OFF · manual</option>
          </select>
        </label>
        <button type="button" className="tlog-btn" onClick={() => setTick((t) => t + 1)}>REFRESH</button>
        <datalist id="tst-devices">{deviceOptions.map((d) => <option key={d} value={d} />)}</datalist>
        <datalist id="tst-sites">{siteOptions.map((s) => <option key={s} value={s} />)}</datalist>
      </form>

      <div className="tst-section-title">
        <span>DEVICES / SOURCES SEEN ({sources ? sources.items.length : '—'}) · {windowKey === 'custom' ? 'last 24 hours' : WINDOWS.find((w) => w.key === windowKey)?.label.toLowerCase()} · click a row to filter the stream</span>
      </div>
      <div className="tlog-table-wrap tst-sources">
        <table className="tlog-table tst-table-compact" data-testid="sources-table">
          <thead><tr>
            <th>Device ID</th><th>Site ID</th><th>Protocol</th><th>Source IP</th><th>Last Seen</th><th>Status</th>
            <th className="tst-num">Last Flow</th><th className="tst-num">Today Total</th><th className="tst-num">Signal</th>
            <th className="tst-num">Packets</th><th>Last Result</th>
          </tr></thead>
          <tbody>
            {!sources && <tr><td colSpan={11} className="tlog-muted">Loading…</td></tr>}
            {sources && sources.items.length === 0 && <tr><td colSpan={11} className="tlog-muted">Nothing received in this window.</td></tr>}
            {(sources?.items || []).map((s) => {
              const st = sourceStatus(s, serverNowMs);
              return (
                <tr key={s.key} className="row tst-click" onClick={() => focusSource(s)} data-key={s.key}>
                  <td className="tlog-nowrap">{s.device_id || 'UNKNOWN'}{s.device_name ? <div className="tlog-muted">{s.device_name}</div> : null}</td>
                  <td className="tlog-nowrap">{dash(s.site_id)}</td>
                  <td><ProtoBadge protocol={s.protocol} label={s.protocol_label} /></td>
                  <td className="tlog-nowrap">{s.protocol === 'TCP' ? dash(s.source_ip) : 'broker'}</td>
                  <td className="tlog-nowrap">{s.last_seen_at_display}</td>
                  <td><span className={`tst-st ${st}`} data-status={st}>{st.toUpperCase()}</span></td>
                  <td className="tst-num">{s.last_flow != null ? `${fmtNum(s.last_flow, 2)} ${s.last_flow_unit || ''}` : '—'}</td>
                  <td className="tst-num">{s.last_total_today != null ? fmtNum(s.last_total_today, 2) : '—'}</td>
                  <td className="tst-num">{dash(s.last_signal_dbm)}</td>
                  <td className="tst-num">{s.packet_count}</td>
                  <td><PacketStatus status={s.last_status} outcome={s.last_result} /> <span className="tlog-muted">{s.last_result || ''}</span></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="tst-section-title">
        <span>LIVE PACKET STREAM · newest first · {packets ? `${packets.total.toLocaleString('en-IN')} packet(s)` : '—'}</span>
        <span>{auto ? `AUTO REFRESH: ${intervalS}s` : 'AUTO REFRESH: OFF'}</span>
      </div>
      <div className={`tst-split${openId != null ? ' has-detail' : ''}`}>
      <div className="tlog-table-wrap tst-stream">
        <table className="tlog-table tst-table-compact" data-testid="packet-table">
          <thead><tr>
            <th>TIME</th><th>PROTOCOL</th><th>DEVICE</th><th>SITE</th><th>SOURCE</th><th>STATUS</th>
            <th className="tst-num">SIZE</th><th className="tst-num">FLOW</th><th className="tst-num">TODAY</th><th>RESULT</th>
          </tr></thead>
          <tbody>
            {!packets && !error && <tr><td colSpan={10} className="tlog-muted">Loading…</td></tr>}
            {packets && items.length === 0 && <tr><td colSpan={10} className="tlog-muted">No packets match.</td></tr>}
            {items.map((p) => (
              <tr key={p.id} className={`row tst-click ${STATUS_CLASS[p.status] || ''}${openId === p.id ? ' sel' : ''}`} onClick={() => setOpenId(p.id)} data-id={p.id}>
                <td className="tlog-nowrap">{p.received_at_display}</td>
                <td><ProtoBadge protocol={p.protocol} label={p.protocol_label} /></td>
                <td className="tlog-nowrap">{p.status === 'INVALID' || !p.device_id ? 'UNKNOWN' : (p.device_name || p.device_id)}</td>
                <td className="tlog-nowrap">{p.status === 'INVALID' ? '—' : dash(p.site_id)}</td>
                <td className="tlog-nowrap">{p.protocol === 'TCP' ? dash(p.source_ip) : 'broker'}</td>
                <td><PacketStatus status={p.status} outcome={p.outcome} /></td>
                <td className="tst-num">{p.size} bytes</td>
                <td className="tst-num">{p.flow != null ? fmtNum(p.flow, 2) : '—'}</td>
                <td className="tst-num">{p.total_today != null ? fmtNum(p.total_today, 2) : '—'}</td>
                <td className="tlog-nowrap">{p.outcome || '—'}{p.error_reason ? <div className="tlog-reason" title={p.error_reason}>{p.error_reason}</div> : null}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {openId != null && <PacketDetail id={openId} onClose={closeDetail} />}
      </div>

      <div className="tlog-foot">
        <button type="button" className="tlog-btn" disabled={page <= 1} onClick={() => setPage((x) => Math.max(1, x - 1))}>◀ PREV</button>
        <span data-testid="packet-page">Page {packets ? packets.page : page} of {packets ? packets.total_pages : 1}</span>
        <button type="button" className="tlog-btn" disabled={!packets || page >= packets.total_pages} onClick={() => setPage((x) => x + 1)}>NEXT ▶</button>
        <label>Rows
          <select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }} aria-label="Rows per page">
            {DIAG_PAGE_SIZES.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <span className="tlog-muted">Times are server receipt times (IST). Records are kept {summary?.retention_days ?? 30} days.</span>
      </div>
    </div>
  );
}
