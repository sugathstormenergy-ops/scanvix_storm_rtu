/**
 * Analytics — history of ONE meter (device-scoped; fleet data is never mixed together).
 *
 * The meter comes from the URL (/analytics?device=<device_id>), so it stays selected when
 * navigating from Production ("Open Analytics") and can be bookmarked. Data: only
 * GET /api/telemetry/{device_id} for the selected window (API maximum 5000 rows, newest
 * first; a full page is flagged as a partial window). Nothing is requested until a meter
 * is selected.
 */
import { useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { useStormData } from '../store/StormDataContext';
import { Card } from '../components/ui/Card';
import { KpiCard } from '../components/ui/KpiCard';
import { ErrorBanner, PageError, PageLoading } from '../components/ui/PageState';
import { EmptyState } from '../components/ui/EmptyState';
import { StatusPill } from '../components/ui/StatusPill';
import { CHART_COLORS, RC_GRID_COLOR, SERIES, rcAxisTick, rcTooltipProps } from '../components/ui/chartTheme';
import MeterSelect from '../components/MeterSelect';
import { useAsyncData } from '../hooks/useAsyncData';
import { fetchDeviceTelemetry, TELEMETRY_MAX_LIMIT } from '../services/stormApi';
import { countBy, dominantFlowUnit, rawSeries } from '../utils/series';
import {
  apiDateKey, displayName, fmtInt, fmtNum, formatApiDateTime, meterStatus, parseApiTimestamp, toApiNaive,
  totalUnitFromFlowUnit,
} from '../utils/meterStatus';

const WINDOWS = [
  { key: '24h', label: 'Last 24 hours', ms: 24 * 3_600_000 },
  { key: '48h', label: 'Last 48 hours', ms: 48 * 3_600_000 },
  { key: '7d', label: 'Last 7 days', ms: 7 * 24 * 3_600_000 },
  { key: '30d', label: 'Last 30 days', ms: 30 * 24 * 3_600_000 },
];

function ChartBox({ height = 240, children }) {
  return <div style={{ width: '100%', height }}>{children}</div>;
}

function avg(values) {
  const v = values.filter((x) => x != null && Number.isFinite(Number(x))).map(Number);
  return v.length ? v.reduce((a, b) => a + b, 0) / v.length : null;
}

function NAcell({ v }) {
  return v === null || v === undefined || v === '' ? <span className="kv-value muted">N/A</span> : <>{String(v)}</>;
}

function SeriesChart({ points, color, name, loading, empty }) {
  if (loading) return <div className="skeleton" style={{ height: 240 }} />;
  if (!points.length) return <EmptyState icon="fa-chart-line" title={empty} />;
  return (
    <ChartBox>
      <ResponsiveContainer>
        <LineChart data={points}>
          <CartesianGrid stroke={RC_GRID_COLOR} vertical={false} />
          <XAxis dataKey="label" tick={rcAxisTick(9)} minTickGap={28} />
          <YAxis tick={rcAxisTick(9)} width={48} />
          <Tooltip {...rcTooltipProps(color)} />
          <Line type="monotone" dataKey="value" name={name} stroke={color} dot={false} strokeWidth={2} isAnimationActive={false} />
        </LineChart>
      </ResponsiveContainer>
    </ChartBox>
  );
}

function DeviceAnalytics({ device, serverTime }) {
  const nowMs = parseApiTimestamp(serverTime);
  const [windowKey, setWindowKey] = useState('24h');
  const [protocol, setProtocol] = useState('');
  const win = WINDOWS.find((w) => w.key === windowKey);

  const res = useAsyncData(
    (signal) => fetchDeviceTelemetry(device.device_id, { from: toApiNaive(nowMs - win.ms), to: serverTime, limit: TELEMETRY_MAX_LIMIT }, signal),
    [device.device_id, windowKey, serverTime],
    { enabled: nowMs != null, keepPrevious: true },
  );
  const all = useMemo(() => (res.data ?? []).filter((r) => r.device_id === device.device_id), [res.data, device.device_id]);
  const rows = useMemo(() => (protocol ? all.filter((r) => r.protocol === protocol) : all), [all, protocol]);
  const truncated = (res.data?.length ?? 0) >= TELEMETRY_MAX_LIMIT;
  const loadingRows = nowMs == null || (res.loading && !res.data);

  const { unit: flowUnit, mixed } = useMemo(() => dominantFlowUnit(rows), [rows]);
  const flow = useMemo(() => rawSeries(rows.filter((r) => !flowUnit || r.flow_unit === flowUnit), 'flow'), [rows, flowUnit]);
  const signal = useMemo(() => rawSeries(rows, 'signal_dbm'), [rows]);
  const battery = useMemo(() => rawSeries(rows, 'battery'), [rows]);
  const pressure = useMemo(() => rawSeries(rows, 'pressure'), [rows]);
  const protocolSplit = useMemo(() => countBy(rows, (r) => r.protocol), [rows]);
  const totalUnit = totalUnitFromFlowUnit(flowUnit);
  // Daily totals: the newest reading of each (IST) calendar day carries that day's running total.
  const daily = useMemo(() => {
    const seen = new Map();
    for (const r of rows) {                     // rows are newest first
      const day = apiDateKey(r.timestamp);
      if (day && !seen.has(day) && r.total_today != null) seen.set(day, r.total_today);
    }
    return [...seen.entries()].map(([day, total]) => ({ day: day.slice(5), total })).reverse();
  }, [rows]);
  const recent = rows.slice(0, 20);
  const last = rows[0];

  return (
    <div className="stack" data-testid="device-analytics">
      <div className="analytics-toolbar">
        <select className="meter-control meter-select" aria-label="Time window" value={windowKey} onChange={(e) => setWindowKey(e.target.value)}>
          {WINDOWS.map((w) => <option key={w.key} value={w.key}>{w.label}</option>)}
        </select>
        <select className="meter-control meter-select" aria-label="Protocol" value={protocol} onChange={(e) => setProtocol(e.target.value)}>
          <option value="">All protocols</option>
          <option value="MQTT">MQTT</option>
          <option value="TCP">TCP</option>
        </select>
        {res.loading && res.data && <span className="page-note"><i className="fa-solid fa-rotate fa-spin" />Updating…</span>}
        {truncated && (
          <span className="page-note" data-testid="truncation-note">
            <i className="fa-solid fa-circle-info" />Partial window: only the newest {fmtInt(TELEMETRY_MAX_LIMIT)} readings were loaded. Choose a shorter window.
          </span>
        )}
        {mixed && <span className="page-note"><i className="fa-solid fa-circle-info" />Only {flowUnit} flow readings are charted</span>}
      </div>

      {res.error && <ErrorBanner message={`Telemetry could not be loaded: ${res.error.message}`} onRetry={res.reload} />}

      <div className="kpi-grid">
        <KpiCard title="Readings in window" value={loadingRows ? null : fmtInt(rows.length)} loading={loadingRows} icon="database" color="blue" />
        <KpiCard title="Last reading" value={loadingRows ? null : (last ? formatApiDateTime(last.timestamp) : 'N/A')} loading={loadingRows} icon="clock" color="green" />
        <KpiCard title={`Avg flow${flowUnit ? ` (${flowUnit})` : ''}`} value={loadingRows ? null : fmtNum(avg(flow.map((p) => p.value)), 3)} loading={loadingRows} icon="water" color="purple" />
        <KpiCard title="Avg signal (dBm)" value={loadingRows ? null : fmtNum(avg(signal.map((p) => p.value)), 1)} loading={loadingRows} icon="signal" color="indigo" />
        <KpiCard title="Avg battery" value={loadingRows ? null : fmtNum(avg(battery.map((p) => p.value)), 2)} loading={loadingRows} icon="battery-half" color="amber" />
        <KpiCard title="Avg pressure" value={loadingRows ? null : fmtNum(avg(pressure.map((p) => p.value)), 2)} loading={loadingRows} icon="gauge" color="teal" />
      </div>

      {!loadingRows && !res.error && rows.length === 0 && (
        <Card className="auto"><EmptyState icon="fa-chart-simple" title="No telemetry in this window" testId="analytics-empty">
          {displayName(device)} sent no readings during the {win.label.toLowerCase()}.
        </EmptyState></Card>
      )}

      <div className="analytics-grid">
        <Card icon="fa-chart-line" title={`Flow${flowUnit ? ` (${flowUnit})` : ''}`}>
          <SeriesChart points={flow} color={SERIES.blue} name="Flow" loading={loadingRows} empty="No flow readings" />
        </Card>
        <Card icon="fa-calendar-day" title={`Daily totals${totalUnit ? ` (${totalUnit})` : ''}`}>
          {loadingRows ? <div className="skeleton" style={{ height: 240 }} /> : daily.length ? (
            <ChartBox>
              <ResponsiveContainer>
                <BarChart data={daily}>
                  <CartesianGrid stroke={RC_GRID_COLOR} vertical={false} />
                  <XAxis dataKey="day" tick={rcAxisTick(9)} />
                  <YAxis tick={rcAxisTick(9)} width={52} />
                  <Tooltip {...rcTooltipProps(SERIES.blue)} />
                  <Bar dataKey="total" name="Total" fill={SERIES.blue} isAnimationActive={false} />
                </BarChart>
              </ResponsiveContainer>
            </ChartBox>
          ) : <EmptyState icon="fa-calendar-day" title="No daily totals reported" />}
        </Card>
        <Card icon="fa-signal" title="Signal (dBm)">
          <SeriesChart points={signal} color={SERIES.indigo} name="Signal" loading={loadingRows} empty="No signal readings" />
        </Card>
        <Card icon="fa-battery-half" title="Battery">
          <SeriesChart points={battery} color={SERIES.amber} name="Battery" loading={loadingRows} empty="No battery readings" />
        </Card>
        <Card icon="fa-gauge" title="Pressure">
          <SeriesChart points={pressure} color={SERIES.teal} name="Pressure" loading={loadingRows} empty="No pressure readings" />
        </Card>
        <Card icon="fa-chart-pie" title="Readings by protocol">
          {loadingRows ? <div className="skeleton" style={{ height: 240 }} /> : rows.length ? (
            <ChartBox>
              <ResponsiveContainer>
                <PieChart>
                  <Tooltip {...rcTooltipProps(SERIES.blue)} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Pie data={protocolSplit} dataKey="value" nameKey="name" outerRadius={80} isAnimationActive={false}>
                    {protocolSplit.map((e, i) => <Cell key={e.name} fill={CHART_COLORS[i % CHART_COLORS.length]} />)}
                  </Pie>
                </PieChart>
              </ResponsiveContainer>
            </ChartBox>
          ) : <EmptyState icon="fa-chart-pie" title="No readings" />}
        </Card>
      </div>

      <Card icon="fa-table" title="Latest readings — registers READ01–READ05 and pressure" className="auto">
        {loadingRows ? <div className="skeleton" style={{ height: 80 }} /> : recent.length ? (
          <div className="table-scroll">
            <table className="meter-table" data-testid="registers-table">
              <thead><tr><th>Reading time</th><th>Protocol</th><th>READ01</th><th>READ02</th><th>READ03</th><th>READ04</th><th>READ05</th><th>Pressure</th></tr></thead>
              <tbody>
                {recent.map((r) => (
                  <tr key={r.id}>
                    <td>{formatApiDateTime(r.timestamp)}</td><td>{r.protocol}</td>
                    {[r.read01, r.read02, r.read03, r.read04, r.read05, r.pressure].map((v, i) => <td key={i}><NAcell v={v} /></td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <EmptyState icon="fa-table" title="No readings in this window" />}
      </Card>
    </div>
  );
}

export default function AnalyticsPage() {
  const { devices, serverTime, loading, hasData, error, refresh } = useStormData();
  const [params, setParams] = useSearchParams();
  const deviceId = params.get('device') || '';
  const device = deviceId ? devices.find((d) => d.device_id === deviceId) : null;
  const nowMs = parseApiTimestamp(serverTime);

  if (loading && !hasData) return <PageLoading label="Loading meters…" />;
  if (!hasData && error) {
    return <div className="content"><PageError title="Cannot load analytics" message={error.message} onRetry={refresh} /></div>;
  }

  return (
    <div className="content" data-testid="page-analytics">
      <Card className="auto card-overflow">
        <div className="prod-head">
          <div>
            <div className="kv-label">METER ANALYTICS</div>
            <div className="prod-meter-title" data-testid="analytics-meter">{device ? displayName(device) : 'No meter selected'}</div>
            {device && (
              <div className="prod-meter-sub">
                Device ID / IMEI: <b>{device.device_id}</b> · Site: <b>{device.site_id || '—'}</b> · <StatusPill status={meterStatus(device, nowMs)} />
                {' · '}<Link className="meter-link" to={`/production?device=${encodeURIComponent(device.device_id)}`}>Open in Production</Link>
              </div>
            )}
          </div>
          <div style={{ flex: 1, minWidth: 260, maxWidth: 560 }}>
            <div className="kv-label" style={{ marginBottom: 4 }}>SELECT METER</div>
            <MeterSelect devices={devices} value={deviceId} serverNowMs={nowMs} onChange={(id) => setParams({ device: id })} />
          </div>
        </div>
      </Card>

      {!deviceId && (
        <Card className="auto">
          <EmptyState icon="fa-magnifying-glass" title="Select a meter" testId="analytics-select-prompt">
            Analytics shows the history of one meter at a time. Choose a meter above, or open it from Production.
          </EmptyState>
        </Card>
      )}
      {deviceId && !device && (
        <Card className="auto">
          <EmptyState icon="fa-circle-question" title="Meter not found in the registry" testId="analytics-not-found">
            “{deviceId}” is not a registered meter.
          </EmptyState>
        </Card>
      )}
      {device && <DeviceAnalytics key={device.device_id} device={device} serverTime={serverTime} />}
    </div>
  );
}
