/**
 * Production — meter monitoring for registered meters (Devices registry only).
 *
 * The selected meter lives in the URL (/production?device=<device_id>) so the view can be
 * bookmarked and shared, and it is carried to Analytics (/analytics?device=<device_id>).
 * Only that one meter's history is requested (GET /api/telemetry/{device_id}).
 * No raw packets here: an Advanced / Diagnostics section links to the Testing page.
 */
import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useStormData } from '../store/StormDataContext';
import { Card } from '../components/ui/Card';
import { KpiCard } from '../components/ui/KpiCard';
import { ErrorBanner, PageError, PageLoading } from '../components/ui/PageState';
import { EmptyState } from '../components/ui/EmptyState';
import { StatusPill } from '../components/ui/StatusPill';
import MeterSelect from '../components/MeterSelect';
import FlowLineChart from '../components/charts/FlowLineChart';
import { useAsyncData } from '../hooks/useAsyncData';
import { fetchDeviceTelemetry, TELEMETRY_MAX_LIMIT } from '../services/stormApi';
import { rawSeries } from '../utils/series';
import {
  STATUS_LABEL, apiDateKey, displayName, fmtNum, formatAge, formatApiDateTime, meterStatus, parseApiTimestamp,
  toApiNaive, totalUnitFromFlowUnit,
} from '../utils/meterStatus';

const TREND_WINDOWS = [
  { key: '24h', label: '24 hours', ms: 24 * 3_600_000 },
  { key: '48h', label: '48 hours', ms: 48 * 3_600_000 },
  { key: '7d', label: '7 days', ms: 7 * 24 * 3_600_000 },
];
const EXTRA_FIELDS = [['read01', 'READ01'], ['read02', 'READ02'], ['read03', 'READ03'], ['read04', 'READ04'], ['read05', 'READ05'], ['pressure', 'Pressure']];

function Val({ v, unit, decimals = 2 }) {
  if (v === null || v === undefined || v === '') return <span className="kv-value muted">N/A</span>;
  return <>{typeof v === 'number' ? fmtNum(v, decimals) : String(v)}{unit ? ` ${unit}` : ''}</>;
}

function MeterDashboard({ device, serverTime }) {
  const nowMs = parseApiTimestamp(serverTime);
  const [win, setWin] = useState('24h');
  const [showEmpty, setShowEmpty] = useState(false);
  const w = TREND_WINDOWS.find((x) => x.key === win);
  const t = device.latest_telemetry;
  const status = meterStatus(device, nowMs);
  const totalUnit = totalUnitFromFlowUnit(t?.flow_unit);
  const todayIsCurrent = t && apiDateKey(t.timestamp) === apiDateKey(serverTime);

  const trend = useAsyncData(
    (signal) => fetchDeviceTelemetry(device.device_id, { from: toApiNaive(nowMs - w.ms), to: serverTime, limit: TELEMETRY_MAX_LIMIT }, signal),
    [device.device_id, win, serverTime],
    { enabled: nowMs != null, keepPrevious: true },
  );
  const series = useMemo(() => (trend.data ? rawSeries(trend.data, 'flow') : []), [trend.data]);
  const extras = EXTRA_FIELDS.filter(([k]) => showEmpty || (t && t[k] !== null && t[k] !== undefined && t[k] !== ''));

  return (
    <div className="stack" data-testid="meter-dashboard">
      <Card className="auto">
        <div className="prod-head">
          <div>
            <div className="prod-meter-title" data-testid="meter-name">{displayName(device)}</div>
            <div className="prod-meter-sub">
              Device ID / IMEI: <b>{device.device_id}</b>{device.imei && device.imei !== device.device_id ? ` · IMEI ${device.imei}` : ''} · Site: <b>{device.site_id || '—'}</b>
            </div>
          </div>
          <div className="prod-actions">
            <StatusPill status={status} />
            <Link className="meter-btn primary" data-testid="open-analytics" to={`/analytics?device=${encodeURIComponent(device.device_id)}`}>
              <i className="fa-solid fa-chart-line" style={{ marginRight: 6 }} />Open Analytics
            </Link>
          </div>
        </div>
        <div className="kv-grid" style={{ marginTop: 12 }}>
          <div className="kv-item"><div className="kv-label">Communication protocol</div><div className="kv-value">{t?.protocol || device.communication_mode || '—'}</div></div>
          <div className="kv-item"><div className="kv-label">Sensor type</div><div className="kv-value"><Val v={t?.sensor_type} /></div></div>
          <div className="kv-item"><div className="kv-label">Last seen</div><div className="kv-value">{device.last_seen_at ? `${formatApiDateTime(device.last_seen_at)} (${formatAge(device.last_seen_at, nowMs)})` : 'Never'}</div></div>
          <div className="kv-item"><div className="kv-label">Status</div><div className="kv-value">{STATUS_LABEL[status]}</div></div>
        </div>
      </Card>

      <div className="kpi-grid" data-testid="meter-kpis">
        <KpiCard title={`Current flow${t?.flow_unit ? ` (${t.flow_unit})` : ''}`} value={t?.flow != null ? fmtNum(t.flow, 2) : 'N/A'} icon="water" color="blue" />
        <KpiCard title={`Today's total${totalUnit ? ` (${totalUnit})` : ''}`} value={t?.total_today != null && todayIsCurrent ? fmtNum(t.total_today, 2) : 'N/A'}
          subtitle={t?.total_today != null && !todayIsCurrent ? `last reported ${formatApiDateTime(t.timestamp)}` : undefined} icon="calendar-day" color="green" />
        <KpiCard title={`Yesterday's total${totalUnit ? ` (${totalUnit})` : ''}`} value={t?.total_yesterday != null ? fmtNum(t.total_yesterday, 2) : 'N/A'} icon="calendar" color="indigo" />
        <KpiCard title="Signal (dBm)" value={t?.signal_dbm != null ? String(t.signal_dbm) : 'N/A'} icon="signal" color="teal" />
        <KpiCard title="Battery" value={t?.battery != null ? fmtNum(t.battery, 2) : 'N/A'} icon="battery-half" color="amber" />
        <KpiCard title="Meter status" value={STATUS_LABEL[status]} icon="circle-check" color={status === 'online' ? 'green' : status === 'delayed' ? 'amber' : 'rose'} />
      </div>

      <div className="prod-grid-2">
        <Card icon="fa-chart-line" title={`Flow trend — last ${w.label}${t?.flow_unit ? ` (${t.flow_unit})` : ''}`} className="auto"
          action={(
            <select className="meter-control meter-select" aria-label="Trend window" value={win} onChange={(e) => setWin(e.target.value)}>
              {TREND_WINDOWS.map((x) => <option key={x.key} value={x.key}>{x.label}</option>)}
            </select>
          )}>
          <div style={{ height: 260 }} data-testid="flow-trend">
            {trend.loading && !trend.data && <div className="skeleton" style={{ height: '100%', borderRadius: 10 }} />}
            {trend.error && <ErrorBanner message={trend.error.message} onRetry={trend.reload} />}
            {trend.data && !trend.error && (series.length
              ? <FlowLineChart points={series} unit={t?.flow_unit} />
              : <EmptyState icon="fa-chart-line" title={`No flow readings in the last ${w.label}`} />)}
          </div>
        </Card>
        <div className="stack">
          <Card icon="fa-calendar-day" title="Today total" className="auto">
            <div className="prod-total" data-testid="today-total">{t?.total_today != null && todayIsCurrent ? fmtNum(t.total_today, 2) : 'N/A'}<span className="u">{totalUnit || ''}</span></div>
          </Card>
          <Card icon="fa-calendar" title="Yesterday total" className="auto">
            <div className="prod-total" data-testid="yesterday-total">{t?.total_yesterday != null ? fmtNum(t.total_yesterday, 2) : 'N/A'}<span className="u">{totalUnit || ''}</span></div>
          </Card>
          <Card icon="fa-tower-broadcast" title="Communication status" className="auto">
            <div className="kv-grid" data-testid="comm-status">
              <div className="kv-item"><div className="kv-label">Last received</div><div className="kv-value">{t ? formatApiDateTime(t.received_at) : 'Never'}</div></div>
              <div className="kv-item"><div className="kv-label">Age</div><div className="kv-value">{formatAge(device.last_seen_at, nowMs)}</div></div>
              <div className="kv-item"><div className="kv-label">Protocol</div><div className="kv-value">{t?.protocol || '—'}</div></div>
              <div className="kv-item"><div className="kv-label">Signal</div><div className="kv-value">{t?.signal_dbm != null ? `${t.signal_dbm} dBm` : 'N/A'}</div></div>
            </div>
          </Card>
        </div>
      </div>

      <Card icon="fa-table-list" title="Additional data (latest reading)" className="auto"
        action={<label className="page-note"><input type="checkbox" checked={showEmpty} onChange={(e) => setShowEmpty(e.target.checked)} /> Show empty fields</label>}>
        {extras.length ? (
          <div className="kv-grid" data-testid="additional-data">
            {extras.map(([k, label]) => (
              <div className="kv-item" key={k}><div className="kv-label">{label}</div><div className="kv-value"><Val v={t?.[k]} /></div></div>
            ))}
          </div>
        ) : <div className="page-note" data-testid="additional-data-empty">No additional register or pressure values reported.</div>}
      </Card>

      <details className="prod-advanced card auto">
        <summary>Advanced / Diagnostics</summary>
        <p className="page-note" style={{ marginTop: 8 }}>
          Raw packets, parser results and HEX dumps for this meter are on the Testing page.{' '}
          <Link className="meter-link" to={`/testing?device=${encodeURIComponent(device.device_id)}`}>Open in Testing</Link>
        </p>
      </details>
    </div>
  );
}

export default function ProductionPage() {
  const { devices, serverTime, loading, error, hasData, refresh } = useStormData();
  const [params, setParams] = useSearchParams();
  const deviceId = params.get('device') || '';
  const nowMs = parseApiTimestamp(serverTime);
  const device = deviceId ? devices.find((d) => d.device_id === deviceId) : null;

  if (loading && !hasData) return <PageLoading label="Loading meters…" />;
  if (!hasData && error) return <div className="content"><PageError title="Cannot load meters" message={error.message} onRetry={refresh} /></div>;

  return (
    <div className="content" data-testid="page-production">
      {error && <ErrorBanner message={`Refresh failed: ${error.message}. Showing the last successful data.`} onRetry={refresh} />}
      <Card className="auto card-overflow">
        <div className="prod-head">
          <div className="prod-brand">
            <div className="eyebrow">STORM ENERGY</div>
            <h1>Production Monitoring</h1>
          </div>
          <div style={{ flex: 1, minWidth: 260, maxWidth: 560 }}>
            <div className="kv-label" style={{ marginBottom: 4 }}>SELECT METER</div>
            <MeterSelect devices={devices} value={deviceId} serverNowMs={nowMs}
              onChange={(id) => setParams({ device: id })} />
          </div>
        </div>
      </Card>

      {!deviceId && (
        <Card className="auto">
          <EmptyState icon="fa-magnifying-glass" title="Select a meter" testId="production-select-prompt">
            {devices.length
              ? `Choose one of ${devices.length} registered meter(s) to see its flow, totals and communication status.`
              : 'No meters are registered yet. Meters appear here once they are added to the registry.'}
          </EmptyState>
        </Card>
      )}
      {deviceId && !device && (
        <Card className="auto">
          <EmptyState icon="fa-circle-question" title="Meter not found in the registry" testId="production-not-found">
            “{deviceId}” is not a registered meter. Unregistered senders are only visible on the Testing page.
          </EmptyState>
        </Card>
      )}
      {device && <MeterDashboard key={device.device_id} device={device} serverTime={serverTime} />}
    </div>
  );
}
