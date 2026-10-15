/**
 * Consumer Analytics - one meter at a time.
 *   Search        : registered meters only (MeterSelect over GET /api/devices/latest), by device ID,
 *                   name, IMEI or site. The choice lives in the URL (?device=<device_id>).
 *   Comparison    : GET /api/analytics/devices/{id}/consumption - last 24 h, yesterday, last month.
 *                   Consumption is in KL only when the unit converts safely (see backend).
 *   Trend         : GET /api/analytics/devices/{id}/trend - bucketed server-side (24h | 7d | 30d).
 *   History table : GET /api/analytics/devices/{id}/history - paginated; sort/filter act on the page.
 * Nothing is requested, and no chart is drawn, until a meter is selected.
 */
import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useStormData } from '../store/StormDataContext';
import { Card } from '../components/ui/Card';
import { DataPanel } from '../components/ui/DataPanel';
import { EmptyState } from '../components/ui/EmptyState';
import { ErrorBanner, PageError, PageLoading } from '../components/ui/PageState';
import { StatusPill, SortIndicator } from '../components/ui/StatusPill';
import MeterSelect from '../components/MeterSelect';
import BarChart from '../components/charts/BarChart';
import FlowLineChart from '../components/charts/FlowLineChart';
import { useAsyncData } from '../hooks/useAsyncData';
import { fetchDeviceConsumption, fetchDeviceHistory, fetchDeviceTrend } from '../services/stormApi';
import { formatApiDateTime, formatApiShort, fmtNum, meterStatus, parseApiTimestamp, displayName } from '../utils/meterStatus';
import './Pages.css';

const TREND_WINDOWS = [['24h', '24 hours'], ['7d', '7 days'], ['30d', '30 days']];
const PAGE_SIZES = [25, 50, 100];
const PERIOD_COLOR = { last_24h: '#6C9BFF', yesterday: '#34D399', last_month: '#B9A7FF' };
const COLUMNS = [
  { key: 'timestamp', label: 'Timestamp', get: (r) => parseApiTimestamp(r.timestamp) },
  { key: 'flow', label: 'Flow', right: true, get: (r) => r.flow },
  { key: 'flow_unit', label: 'Flow Unit', get: (r) => r.flow_unit || '' },
  { key: 'total_today', label: 'Total Today', right: true, get: (r) => r.total_today },
  { key: 'total_yesterday', label: 'Total Yesterday', right: true, get: (r) => r.total_yesterday },
  { key: 'signal_dbm', label: 'Signal (dBm)', right: true, get: (r) => r.signal_dbm },
  { key: 'battery', label: 'Battery', right: true, get: (r) => r.battery },
  { key: 'protocol', label: 'Protocol', get: (r) => r.protocol || '' },
];

function PeriodCard({ p, flowUnit }) {
  const noReadings = p.readings === 0 && p.consumption_kl == null && p.consumption_raw == null;
  let consumption = '—';
  let note = null;
  if (p.consumption_kl != null) consumption = `${fmtNum(p.consumption_kl, 2)} KL`;
  else if (!p.unit_convertible) { consumption = '—'; note = `Unit ${p.total_unit || 'unknown'} cannot be converted to KL`; }
  else if (noReadings) note = 'No readings in this period';
  return (
    <div className="ca-period" data-testid={`period-${p.key}`} style={{ borderTopColor: PERIOD_COLOR[p.key] }}>
      <div className="ca-period-label">{p.label}</div>
      <div className="ca-period-value" data-testid={`period-${p.key}-value`}>{consumption}</div>
      {note && <div className="ca-period-note">{note}</div>}
      <dl className="ca-period-stats">
        <div><dt>Avg flow</dt><dd>{p.flow_avg != null ? `${fmtNum(p.flow_avg, 2)} ${flowUnit || ''}` : '—'}</dd></div>
        <div><dt>Peak flow</dt><dd>{p.flow_max != null ? `${fmtNum(p.flow_max, 2)} ${flowUnit || ''}` : '—'}</dd></div>
        <div><dt>Min flow</dt><dd>{p.flow_min != null ? `${fmtNum(p.flow_min, 2)} ${flowUnit || ''}` : '—'}</dd></div>
        <div><dt>Readings</dt><dd>{p.readings}</dd></div>
      </dl>
    </div>
  );
}

function HistoryTable({ deviceId }) {
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [order, setOrder] = useState('desc');
  const [filter, setFilter] = useState('');
  const [sort, setSort] = useState({ key: null, dir: 'asc' });
  const res = useAsyncData((signal) => fetchDeviceHistory(deviceId, { page, pageSize, order }, signal),
    [deviceId, page, pageSize, order], { keepPrevious: true });
  const data = res.data;
  const pages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  const rows = useMemo(() => {
    let list = data?.items ?? [];
    const q = filter.trim().toLowerCase();
    if (q) list = list.filter((r) => COLUMNS.some((c) => String(c.get(r) ?? '').toLowerCase().includes(q)
      || (c.key === 'timestamp' && formatApiDateTime(r.timestamp).toLowerCase().includes(q))));
    if (sort.key) {
      const col = COLUMNS.find((c) => c.key === sort.key);
      const dir = sort.dir === 'asc' ? 1 : -1;
      list = [...list].sort((a, b) => {
        const va = col.get(a); const vb = col.get(b);
        if (va == null && vb == null) return 0;
        if (va == null) return 1;
        if (vb == null) return -1;
        return va < vb ? -dir : va > vb ? dir : 0;
      });
    }
    return list;
  }, [data, filter, sort]);

  const onSort = (key) => {
    if (key === 'timestamp') { setOrder((o) => (o === 'desc' ? 'asc' : 'desc')); setSort({ key: null, dir: 'asc' }); setPage(1); return; }
    setSort((s) => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' }));
  };

  if (res.error && !data) return <DataPanel title="Historical data" icon="fa-table-list" error={res.error} onRetry={res.reload} />;
  if (!data && res.loading) return <DataPanel title="Historical data" icon="fa-table-list" loading hasData={false} />;
  if (data && data.total === 0) return <DataPanel title="Historical data" icon="fa-table-list" hasData={false} emptyText="This meter has no telemetry yet" testId="history" />;

  return (
    <Card icon="fa-table-list" title="Historical data" className="auto ca-history"
      action={<input className="meter-control meter-search" type="search" aria-label="Filter rows on this page" placeholder="Filter this page…"
        value={filter} onChange={(e) => setFilter(e.target.value)} />}>
      {res.error && <ErrorBanner message={res.error.message} onRetry={res.reload} />}
      <div className="table-scroll ca-history-scroll">
        <table className="meter-data-table" data-testid="history-table">
          <thead>
            <tr>
              {COLUMNS.map((c) => {
                const active = c.key === 'timestamp' ? true : sort.key === c.key;
                const dir = c.key === 'timestamp' ? (order === 'desc' ? 'desc' : 'asc') : sort.dir;
                return (
                  <th key={c.key} data-sort={c.key} className={c.right ? 'align-right' : undefined} onClick={() => onSort(c.key)}
                    aria-sort={active ? (dir === 'asc' ? 'ascending' : 'descending') : 'none'}>
                    {c.label} <SortIndicator col={c.key} sortKey={active ? c.key : null} sortDir={dir} />
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && <tr className="empty-row"><td colSpan={COLUMNS.length}>No rows on this page match the filter.</td></tr>}
            {rows.map((r) => (
              <tr key={r.id}>
                <td>{formatApiDateTime(r.timestamp)}</td>
                <td className="align-right">{fmtNum(r.flow, 3)}</td>
                <td>{r.flow_unit || '—'}</td>
                <td className="align-right">{fmtNum(r.total_today, 2)}</td>
                <td className="align-right">{fmtNum(r.total_yesterday, 2)}</td>
                <td className="align-right">{r.signal_dbm ?? '—'}</td>
                <td className="align-right">{fmtNum(r.battery, 2)}</td>
                <td>{r.protocol}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="table-footer">
        <div className="range-summary">
          {`Rows ${(data.page - 1) * data.page_size + 1}–${Math.min(data.page * data.page_size, data.total)} of ${data.total}`}
        </div>
        <div className="pagination-controls">
          <div className="page-buttons">
            <button type="button" className="page-number" disabled={page <= 1} onClick={() => setPage(page - 1)} aria-label="Previous page">‹</button>
            <span className="page-ellipsis" data-testid="history-page">Page {page} / {pages}</span>
            <button type="button" className="page-number" disabled={page >= pages} onClick={() => setPage(page + 1)} aria-label="Next page">›</button>
          </div>
        </div>
        <label className="page-size-label">
          <select className="meter-control meter-select" aria-label="Rows per page" value={pageSize}
            onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}>
            {PAGE_SIZES.map((n) => <option key={n} value={n}>{n} per page</option>)}
          </select>
        </label>
      </div>
    </Card>
  );
}

function MeterAnalytics({ device, serverTime }) {
  const nowMs = parseApiTimestamp(serverTime);
  const [win, setWin] = useState('24h');
  const status = meterStatus(device, nowMs);
  const cons = useAsyncData((signal) => fetchDeviceConsumption(device.device_id, signal), [device.device_id]);
  const trend = useAsyncData((signal) => fetchDeviceTrend(device.device_id, win, signal), [device.device_id, win], { keepPrevious: true });

  const periods = cons.data?.periods ?? [];
  const flowUnit = cons.data?.flow_unit ?? trend.data?.flow_unit ?? null;
  const barItems = periods.map((p) => ({ label: p.label, value: p.consumption_kl, color: PERIOD_COLOR[p.key] }));
  const points = useMemo(() => (trend.data?.points ?? []).map((p) => ({ label: formatApiShort(p.t), value: p.avg })), [trend.data]);

  return (
    <div className="stack" data-testid="meter-analytics">
      <Card className="auto">
        <div className="ca-head">
          <div>
            <div className="eyebrow">Consumer / Meter Analytics</div>
            <h2 className="ca-title" data-testid="ca-meter-name">{displayName(device)}</h2>
          </div>
          <dl className="ca-head-facts">
            <div><dt>Meter</dt><dd data-testid="ca-meter-id">{device.device_id}</dd></div>
            {device.name && <div><dt>Name</dt><dd>{device.name}</dd></div>}
            {device.site_id && <div><dt>Site</dt><dd>{device.site_id}</dd></div>}
            <div><dt>Status</dt><dd><StatusPill status={status} /></dd></div>
            <div><dt>Last seen</dt><dd>{device.last_seen_at ? formatApiDateTime(device.last_seen_at) : 'Never'}</dd></div>
          </dl>
        </div>
      </Card>

      {cons.error && <ErrorBanner message={cons.error.message} onRetry={cons.reload} />}
      {cons.loading && !cons.data && <div className="skeleton" style={{ height: 96, borderRadius: 12 }} />}
      {periods.length > 0 && (
        <section className="ca-periods" data-testid="period-cards">
          {periods.map((p) => <PeriodCard key={p.key} p={p} flowUnit={flowUnit} />)}
        </section>
      )}

      <div className="ov-panels">
        <DataPanel title="Consumption comparison (KL)" icon="fa-chart-column" testId="compare-chart" height={230}
          hasData={barItems.some((i) => i.value != null)} loading={cons.loading} error={null}
          emptyText="No convertible consumption to compare for this meter">
          <BarChart items={barItems} unit="KL" ariaLabel="Consumption: last 24 hours vs yesterday vs last month" />
        </DataPanel>
        <DataPanel title={`Flow trend - last ${TREND_WINDOWS.find(([k]) => k === win)[1]}${flowUnit ? ` (${flowUnit})` : ''}`} icon="fa-chart-line"
          testId="trend-chart" height={230} hasData={points.length > 0} loading={trend.loading} error={trend.error} onRetry={trend.reload}
          emptyText="No flow readings in this window"
          action={(
            <select className="meter-control meter-select" aria-label="Trend window" value={win} onChange={(e) => setWin(e.target.value)}>
              {TREND_WINDOWS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </select>
          )}>
          <FlowLineChart points={points} unit={flowUnit} ariaLabel="Average flow trend" />
        </DataPanel>
      </div>

      <HistoryTable deviceId={device.device_id} />
    </div>
  );
}

export default function ConsumerAnalyticsPage() {
  const { devices, serverTime, loading, error, hasData, refresh } = useStormData();
  const [params, setParams] = useSearchParams();
  const deviceId = params.get('device') || '';
  const nowMs = parseApiTimestamp(serverTime);
  const device = deviceId ? devices.find((d) => d.device_id === deviceId) : null;

  if (loading && !hasData) return <PageLoading label="Loading meters…" />;
  if (!hasData && error) return <div className="content"><PageError title="Cannot load meters" message={error.message} onRetry={refresh} /></div>;

  return (
    <div className="content" data-testid="page-consumer">
      {error && <ErrorBanner message={`Refresh failed: ${error.message}. Showing the last successful data.`} onRetry={refresh} />}
      <Card className="auto card-overflow">
        <div className="ca-search">
          <div className="ca-search-label">Search Meter</div>
          <MeterSelect devices={devices} value={deviceId} serverNowMs={nowMs} onChange={(id) => setParams({ device: id })}
            placeholder="Search by meter ID, device ID or name…" />
          {device && <Link className="meter-link" to={`/production?device=${encodeURIComponent(device.device_id)}`}>Open in Production</Link>}
        </div>
      </Card>

      {!deviceId && (
        <div className="panel-note ca-prompt" data-testid="consumer-select-prompt">Search and select a meter to view historical consumption.</div>
      )}
      {deviceId && !device && (
        <EmptyState icon="fa-circle-question" title="Meter not found in the registry" testId="consumer-not-found">
          “{deviceId}” is not a registered meter.
        </EmptyState>
      )}
      {device && <MeterAnalytics key={device.device_id} device={device} serverTime={serverTime} />}
    </div>
  );
}
