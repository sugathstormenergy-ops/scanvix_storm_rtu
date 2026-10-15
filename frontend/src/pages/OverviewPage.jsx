/**
 * Overview - primary operational dashboard.
 *   KPIs        : registry snapshot (GET /api/devices/latest, status by SERVER time) +
 *                 Total Today (KL) from GET /api/analytics/overview (backend-aggregated).
 *   Panels      : status distribution, daily consumption (GET /api/analytics/daily), meters by site.
 *                 A panel with no data collapses to a compact note or is hidden - no big blank areas.
 *   Meter table : searchable/sortable list of registered meters with a detail drawer.
 */
import { useCallback, useMemo, useState } from 'react';
import { useStormData } from '../store/StormDataContext';
import { Card } from '../components/ui/Card';
import { DataPanel } from '../components/ui/DataPanel';
import { ErrorBanner, PageError } from '../components/ui/PageState';
import { StatusPill, SortIndicator } from '../components/ui/StatusPill';
import BarChart from '../components/charts/BarChart';
import DonutChart from '../components/charts/DonutChart';
import MeterDetailPanel from '../components/MeterDetailPanel';
import { useAsyncData } from '../hooks/useAsyncData';
import { fetchAnalyticsDaily, fetchAnalyticsOverview } from '../services/stormApi';
import { getPref } from '../utils/prefs';
import './Pages.css';
import {
  STATUS, STATUS_LABEL, apiDateKey, displayName, fmtInt, fmtNum, formatAge, meterStatus, parseApiTimestamp,
  totalUnitFromFlowUnit,
} from '../utils/meterStatus';

const NO_SITE = '(No site)';
const STATUS_COLOR = { online: '#34D399', delayed: '#F59E0B', stale: '#FF6B6B', offline: '#94A3B8', inactive: '#475b78' };
const STATUS_HELP = 'Online: last seen within 24 h. Delayed: 24-48 h. Stale: over 48 h. Offline: never reported. Active meters only.';
export const TOTAL_TODAY_HELP = 'Sum of consumption of all meters in KL for the last 24 hours';

function siteOf(d) { return d.site_id || NO_SITE; }

function Kpi({ label, value, unit, tone, testId, title, sub, loading }) {
  return (
    <div className={`ov-kpi${tone ? ` ${tone}` : ''}`} data-testid={testId} title={title}>
      <div className="ov-kpi-label">{label}</div>
      <div className="ov-kpi-value">
        {loading ? <span className="skeleton" style={{ display: 'inline-block', width: 56, height: 18, borderRadius: 4 }} /> : value}
        {!loading && unit && value !== '—' ? <span className="ov-kpi-unit">{unit}</span> : null}
      </div>
      {sub && <div className="ov-kpi-sub">{sub}</div>}
    </div>
  );
}

function SiteSummary({ rows, nowMs }) {
  const sites = useMemo(() => {
    const m = new Map();
    for (const d of rows) {
      const k = siteOf(d);
      const s = m.get(k) || { site: k, total: 0, online: 0, delayed: 0, stale: 0, offline: 0, inactive: 0 };
      s.total += 1;
      s[meterStatus(d, nowMs)] += 1;
      m.set(k, s);
    }
    return [...m.values()].sort((a, b) => a.site.localeCompare(b.site));
  }, [rows, nowMs]);
  return (
    <div className="site-summary-scroll" style={{ maxHeight: 220 }}>
      <table className="site-summary-table" data-testid="site-summary">
        <thead>
          <tr><th>Site</th><th>Meters</th><th>Online</th><th>Delayed</th><th>Stale</th><th>Offline</th><th>Inactive</th></tr>
        </thead>
        <tbody>
          {sites.map((s) => (
            <tr key={s.site}>
              <td>{s.site}</td><td>{fmtInt(s.total)}</td><td>{fmtInt(s.online)}</td><td>{fmtInt(s.delayed)}</td>
              <td>{fmtInt(s.stale)}</td><td>{fmtInt(s.offline)}</td><td>{fmtInt(s.inactive)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const COLUMNS = [
  { key: 'name', label: 'Meter' },
  { key: 'site', label: 'Site' },
  { key: 'status', label: 'Status' },
  { key: 'last_seen', label: 'Last seen' },
  { key: 'flow', label: 'Flow', right: true },
  { key: 'total_today', label: 'Total today', right: true },
  { key: 'total_yesterday', label: 'Total yesterday', right: true },
  { key: 'signal', label: 'Signal (dBm)', right: true },
  { key: 'battery', label: 'Battery', right: true },
  { key: 'protocol', label: 'Protocol' },
];
const STATUS_ORDER = { online: 0, delayed: 1, stale: 2, offline: 3, inactive: 4 };

function sortValue(d, key, nowMs, todayKey) {
  const t = d.latest_telemetry;
  switch (key) {
    case 'name': return displayName(d).toLowerCase();
    case 'site': return siteOf(d).toLowerCase();
    case 'status': return STATUS_ORDER[meterStatus(d, nowMs)];
    case 'last_seen': return parseApiTimestamp(d.last_seen_at) ?? -Infinity;
    case 'flow': return t?.flow ?? -Infinity;
    case 'total_today': return t && apiDateKey(t.timestamp) === todayKey ? (t.total_today ?? -Infinity) : -Infinity;
    case 'total_yesterday': return t?.total_yesterday ?? -Infinity;
    case 'signal': return t?.signal_dbm ?? -Infinity;
    case 'battery': return t?.battery ?? -Infinity;
    case 'protocol': return t?.protocol ?? '';
    default: return 0;
  }
}

function pageList(page, pages) {
  if (pages <= 7) return Array.from({ length: pages }, (_, i) => i + 1);
  const set = new Set([1, pages, page - 1, page, page + 1].filter((p) => p >= 1 && p <= pages));
  const sorted = [...set].sort((a, b) => a - b);
  const out = [];
  sorted.forEach((p, i) => { if (i && p - sorted[i - 1] > 1) out.push('…'); out.push(p); });
  return out;
}

export default function OverviewPage() {
  const { devices, serverTime, kpis, loading, error, hasData, refresh } = useStormData();
  const nowMs = parseApiTimestamp(serverTime);
  const todayKey = kpis?.todayKey ?? null;

  const totalToday = useAsyncData((signal) => fetchAnalyticsOverview(signal), [serverTime], { enabled: hasData, keepPrevious: true });
  const daily = useAsyncData((signal) => fetchAnalyticsDaily(7, signal), [serverTime], { enabled: hasData, keepPrevious: true });
  const totalKl = totalToday.data?.total_kl ?? null;
  const excluded = totalToday.data?.meters_excluded ?? 0;
  const statusItems = useMemo(() => (kpis ? ['online', 'delayed', 'stale', 'offline', 'inactive'].map((k) => (
    { label: STATUS_LABEL[k], value: kpis[k], color: STATUS_COLOR[k] })) : []), [kpis]);
  const dailyItems = useMemo(() => (daily.data?.days ?? []).map((d) => ({ label: d.date.slice(5), value: d.kl })), [daily.data]);

  const [query, setQuery] = useState('');
  const [site, setSite] = useState('');
  const [status, setStatus] = useState('');
  const [sortKey, setSortKey] = useState('name');
  const [sortDir, setSortDir] = useState('asc');
  const [page, setPage] = useState(1);
  const [pageSize] = useState(() => getPref('pageSize'));
  const [selectedId, setSelectedId] = useState(null);

  const sites = useMemo(() => [...new Set(devices.map(siteOf))].sort(), [devices]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const list = devices.filter((d) => {
      if (site && siteOf(d) !== site) return false;
      if (status && meterStatus(d, nowMs) !== status) return false;
      if (!q) return true;
      return [d.device_id, d.name, d.imei, d.site_id].some((v) => v && String(v).toLowerCase().includes(q));
    });
    const dir = sortDir === 'asc' ? 1 : -1;
    return list.sort((a, b) => {
      const va = sortValue(a, sortKey, nowMs, todayKey);
      const vb = sortValue(b, sortKey, nowMs, todayKey);
      if (va < vb) return -dir;
      if (va > vb) return dir;
      return a.device_id.localeCompare(b.device_id);
    });
  }, [devices, query, site, status, sortKey, sortDir, nowMs, todayKey]);

  const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const current = Math.min(page, pages);
  const pageRows = filtered.slice((current - 1) * pageSize, current * pageSize);
  const selected = selectedId ? devices.find((d) => d.device_id === selectedId) : null;
  const closeDrawer = useCallback(() => setSelectedId(null), []);

  const onSort = (key) => {
    if (key === sortKey) setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    else { setSortKey(key); setSortDir('asc'); }
  };
  const resetFilters = () => { setQuery(''); setSite(''); setStatus(''); setPage(1); };

  return (
    <div className="content" data-testid="page-overview">
      {!hasData && error && <PageError title="Cannot load meters" message={error.message} onRetry={refresh} />}
      {error && hasData && (
        <ErrorBanner message={`Refresh failed: ${error.message}. Showing the last successful data.`} onRetry={refresh} />
      )}

      <section className="ov-kpis" data-testid="hero-kpis">
        <Kpi testId="kpi-total" label="Total Meters" value={kpis ? fmtInt(kpis.total) : '—'} loading={loading && !hasData}
          title={kpis ? `${fmtInt(kpis.inactive)} inactive` : undefined} />
        <Kpi testId="kpi-active" label="Active" value={kpis ? fmtInt(kpis.active) : '—'} loading={loading && !hasData}
          sub={kpis && kpis.offline > 0 ? `${fmtInt(kpis.offline)} never reported` : undefined} />
        <Kpi testId="kpi-online" label="Online (≤ 24 h)" value={kpis ? fmtInt(kpis.online) : '—'} tone="success" loading={loading && !hasData}
          title={STATUS_HELP} />
        <Kpi testId="kpi-delayed" label="Delayed (> 24 h)" value={kpis ? fmtInt(kpis.delayed) : '—'} tone="warning" loading={loading && !hasData}
          title={STATUS_HELP} />
        <Kpi testId="kpi-stale" label="Stale (>48 hr)" value={kpis ? fmtInt(kpis.stale) : '—'} tone="danger" loading={loading && !hasData}
          title={STATUS_HELP} />
        <Kpi testId="kpi-total-today" label="Total Today (KL)" value={totalKl != null ? fmtNum(totalKl, 2) : '—'} unit="KL"
          loading={hasData && totalToday.loading && !totalToday.data} title={TOTAL_TODAY_HELP}
          sub={totalToday.error ? 'Unavailable' : excluded > 0 ? `${excluded} meter(s) excluded: unit not convertible` : undefined} />
      </section>
      <div className="ov-kpi-help" data-testid="total-today-help">{TOTAL_TODAY_HELP}</div>

      {hasData && devices.length > 0 && (
        <section className="ov-panels">
          <DataPanel title="Meter status" icon="fa-tower-broadcast" hasData={statusItems.some((i) => i.value > 0)} height={190} testId="status-chart"
            emptyText="No meters registered">
            <DonutChart items={statusItems} ariaLabel="Meters by communication status" />
          </DataPanel>
          <DataPanel title="Daily consumption (KL) - last 7 days" icon="fa-chart-column" testId="daily-chart" height={190}
            hasData={dailyItems.some((i) => i.value != null)} loading={daily.loading} error={daily.error} onRetry={daily.reload}
            emptyText="No consumption reported in the last 7 days">
            <BarChart items={dailyItems} unit="KL" ariaLabel="Daily consumption in KL" />
          </DataPanel>
          <Card icon="fa-location-dot" title="Meters by site" className="auto site-summary-card">
            <SiteSummary rows={devices} nowMs={nowMs} />
          </Card>
        </section>
      )}

      {hasData && devices.length === 0 && (
        <Card icon="fa-table-list" title="Meters" className="auto panel-compact">
          <div className="panel-note" data-testid="no-meters">No meters are registered yet. Meters appear here after they are added to the registry.</div>
        </Card>
      )}

      {(devices.length > 0 || (!hasData && loading)) && (
      <section className="meter-workspace">
        <div className="meter-toolbar">
          <div className="meter-filter-group">
            <input className="meter-control meter-search" type="search" placeholder="Search meter, name, IMEI, site…"
              aria-label="Search meters" value={query} onChange={(e) => { setQuery(e.target.value); setPage(1); }} />
            <select className="meter-control meter-select" aria-label="Filter by site" value={site} onChange={(e) => { setSite(e.target.value); setPage(1); }}>
              <option value="">All sites</option>
              {sites.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <select className="meter-control meter-select" aria-label="Filter by status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
              <option value="">All statuses</option>
              {Object.values(STATUS).map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
            </select>
            <button type="button" className="meter-btn" onClick={resetFilters}>Reset</button>
          </div>
          <div className="toolbar-divider" />
          <div className="table-summary"><strong>{fmtInt(filtered.length)}</strong> of {fmtInt(devices.length)} meters</div>
        </div>

        <div className="table-scroll">
          <table className="meter-data-table" data-testid="meter-table">
            <thead>
              <tr>
                {COLUMNS.map((c) => (
                  <th key={c.key} data-sort={c.key} className={c.right ? 'align-right' : undefined} onClick={() => onSort(c.key)}
                    aria-sort={sortKey === c.key ? (sortDir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                    {c.label} <SortIndicator col={c.key} sortKey={sortKey} sortDir={sortDir} />
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {loading && !hasData && Array.from({ length: 6 }).map((_, i) => (
                <tr key={i} className="skeleton-row">{COLUMNS.map((c) => <td key={c.key}><span className="skeleton" style={{ display: 'block', height: 12 }} /></td>)}</tr>
              ))}
              {hasData && pageRows.length === 0 && (
                <tr className="empty-row"><td colSpan={COLUMNS.length}>
                  {devices.length === 0 ? 'No meters are registered yet. Meters appear here after they are added to the registry.' : 'No meters match the current filters.'}
                </td></tr>
              )}
              {pageRows.map((d) => {
                const t = d.latest_telemetry;
                const st = meterStatus(d, nowMs);
                const isToday = t && apiDateKey(t.timestamp) === todayKey;
                const tu = totalUnitFromFlowUnit(t?.flow_unit);
                return (
                  <tr key={d.device_id}>
                    <td>
                      <button type="button" className="meter-link" onClick={() => setSelectedId(d.device_id)}>{displayName(d)}</button>
                      {d.name && <div className="table-subtext">{d.device_id}</div>}
                    </td>
                    <td>{d.site_id || '—'}</td>
                    <td><StatusPill status={st} /></td>
                    <td title={d.last_seen_at || ''}>{formatAge(d.last_seen_at, nowMs)}</td>
                    <td className="align-right">{t?.flow != null ? `${fmtNum(t.flow, 3)} ${t.flow_unit || ''}` : '—'}</td>
                    <td className="align-right" title={t && !isToday ? 'Latest reading is not from today' : undefined}>
                      {isToday && t.total_today != null ? `${fmtNum(t.total_today, 2)} ${tu || ''}` : '—'}
                    </td>
                    <td className="align-right">{t?.total_yesterday != null ? `${fmtNum(t.total_yesterday, 2)} ${tu || ''}` : '—'}</td>
                    <td className="align-right">{t?.signal_dbm ?? '—'}</td>
                    <td className="align-right">{fmtNum(t?.battery, 2)}</td>
                    <td>{t?.protocol || '—'}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        <div className="table-footer">
          <div className="range-summary">
            {filtered.length ? `Showing ${(current - 1) * pageSize + 1}–${Math.min(current * pageSize, filtered.length)} of ${filtered.length}` : 'Nothing to show'}
          </div>
          <div className="pagination-controls">
            <div className="page-buttons">
              <button type="button" className="page-number" disabled={current <= 1} onClick={() => setPage(current - 1)} aria-label="Previous page">‹</button>
              {pageList(current, pages).map((p, i) => (p === '…'
                ? <span key={`e${i}`} className="page-ellipsis">…</span>
                : <button type="button" key={p} className={`page-number${p === current ? ' active' : ''}`} onClick={() => setPage(p)}>{p}</button>))}
              <button type="button" className="page-number" disabled={current >= pages} onClick={() => setPage(current + 1)} aria-label="Next page">›</button>
            </div>
          </div>
          <div className="page-size-label">{pageSize} per page</div>
        </div>
      </section>
      )}

      {selected && <MeterDetailPanel device={selected} serverTime={serverTime} onClose={closeDrawer} />}
    </div>
  );
}
