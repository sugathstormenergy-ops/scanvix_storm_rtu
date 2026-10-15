/**
 * MeterDetailPanel — right-hand drawer for one meter (Overview / GIS).
 * Shows the registry record and latest reading from the shared snapshot, plus a
 * 48-hour flow chart and recent events fetched on demand. Read-only.
 */
import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Card } from './ui/Card';
import { StatusPill } from './ui/StatusPill';
import { ErrorBanner } from './ui/PageState';
import { EmptyState } from './ui/EmptyState';
import FlowLineChart from './charts/FlowLineChart';
import { useAsyncData } from '../hooks/useAsyncData';
import { fetchDeviceEvents, fetchDeviceTelemetry } from '../services/stormApi';
import { rawSeries } from '../utils/series';
import {
  displayName, fmtNum, formatAge, formatApiDateTime, hasValidLocation, meterStatus, parseApiTimestamp,
  toApiNaive, totalUnitFromFlowUnit,
} from '../utils/meterStatus';

const WINDOW_MS = 48 * 3_600_000;

function Tile({ label, value, muted = false }) {
  return (
    <div className={`health-tile${muted ? ' na' : ''}`}>
      <div className="health-label">{label}</div>
      <div className={`health-value${muted ? ' muted' : ''}`}>{value}</div>
    </div>
  );
}

export default function MeterDetailPanel({ device, serverTime, onClose }) {
  const nowMs = parseApiTimestamp(serverTime);
  const status = meterStatus(device, nowMs);
  const t = device.latest_telemetry;
  const totalUnit = totalUnitFromFlowUnit(t?.flow_unit);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  const trend = useAsyncData(
    (signal) => fetchDeviceTelemetry(device.device_id, { from: toApiNaive(nowMs - WINDOW_MS), to: serverTime, limit: 5000 }, signal),
    [device.device_id, serverTime],
    { enabled: nowMs != null, keepPrevious: true },
  );
  const events = useAsyncData((signal) => fetchDeviceEvents(device.device_id, signal), [device.device_id]);

  const series = trend.data ? rawSeries(trend.data, 'flow') : [];
  const flowUnit = trend.data?.find((r) => r.flow_unit)?.flow_unit ?? t?.flow_unit ?? null;

  return (
    <div className="meter-drawer-backdrop" onClick={onClose} data-testid="meter-drawer">
      <aside className="meter-drawer" role="dialog" aria-modal="true" aria-label={`Meter ${device.device_id}`} onClick={(e) => e.stopPropagation()}>
        <div className="meter-drawer-head">
          <div>
            <div className="meter-drawer-eyebrow">Meter · {device.site_id || 'No site'}</div>
            <div className="meter-drawer-title">{displayName(device)}</div>
          </div>
          <button type="button" className="meter-drawer-close" onClick={onClose} aria-label="Close"><i className="fa-solid fa-xmark" /></button>
        </div>

        <div className="meter-drawer-body">
          <div className="health-grid">
            <Tile label="Status" value={<StatusPill status={status} />} />
            <Tile label="Last seen" value={device.last_seen_at ? `${formatApiDateTime(device.last_seen_at)} (${formatAge(device.last_seen_at, nowMs)})` : 'Never'} muted={!device.last_seen_at} />
            <Tile label="Device ID" value={device.device_id} />
            <Tile label="IMEI" value={device.imei || '—'} />
            <Tile label="Communication" value={device.communication_mode || '—'} />
            <Tile label="Firmware" value={device.firmware_version || '—'} muted={!device.firmware_version} />
            <Tile label="Location" value={hasValidLocation(device) ? `${Number(device.latitude).toFixed(6)}, ${Number(device.longitude).toFixed(6)}` : 'No location assigned'} muted={!hasValidLocation(device)} />
            <Tile label="Last IP" value={device.last_ip_address || '—'} muted={!device.last_ip_address} />
          </div>

          <Card icon="fa-wave-square" title="Latest reading" className="auto">
            {t ? (
              <div className="health-grid">
                <Tile label="Reading time" value={formatApiDateTime(t.timestamp)} />
                <Tile label="Protocol" value={t.protocol} />
                <Tile label="Flow" value={t.flow != null ? `${fmtNum(t.flow, 3)} ${t.flow_unit || ''}` : '—'} muted={t.flow == null} />
                <Tile label="Total today" value={t.total_today != null ? `${fmtNum(t.total_today, 2)} ${totalUnit || ''}` : '—'} muted={t.total_today == null} />
                <Tile label="Total yesterday" value={t.total_yesterday != null ? `${fmtNum(t.total_yesterday, 2)} ${totalUnit || ''}` : '—'} muted={t.total_yesterday == null} />
                <Tile label="Pressure" value={fmtNum(t.pressure, 2)} muted={t.pressure == null} />
                <Tile label="Signal" value={t.signal_dbm != null ? `${t.signal_dbm} dBm` : '—'} muted={t.signal_dbm == null} />
                <Tile label="Battery" value={fmtNum(t.battery, 2)} muted={t.battery == null} />
                <Tile label="Sensor type" value={t.sensor_type || '—'} muted={!t.sensor_type} />
              </div>
            ) : (
              <EmptyState icon="fa-satellite-dish" title="No telemetry received yet" />
            )}
          </Card>

          <Card icon="fa-chart-line" title={`Flow — last 48 h${flowUnit ? ` (${flowUnit})` : ''}`} className="auto">
            <div style={{ height: 180 }}>
              {trend.loading && !trend.data && <div className="skeleton" style={{ height: '100%', borderRadius: 10 }} />}
              {trend.error && <ErrorBanner message={trend.error.message} onRetry={trend.reload} />}
              {trend.data && !trend.error && (series.length
                ? <FlowLineChart points={series} unit={flowUnit} />
                : <EmptyState icon="fa-chart-line" title="No flow readings in the last 48 hours" />)}
            </div>
          </Card>

          <Card icon="fa-bell" title="Recent events" className="auto">
            {events.loading && <div className="skeleton" style={{ height: 60, borderRadius: 10 }} />}
            {events.error && <ErrorBanner message={events.error.message} onRetry={events.reload} />}
            {events.data && (events.data.length ? (
              <ul className="alert-list">
                {events.data.slice(0, 8).map((e) => (
                  <li key={e.id} className={`alert-item ${e.severity === 'ERROR' || e.severity === 'CRITICAL' ? 'err' : e.severity === 'WARNING' ? 'warn' : 'ok'}`}>
                    <span className="alert-dot" />
                    <div className="alert-body">
                      <div className="alert-title">{e.event_type}</div>
                      <div className="alert-meta">{e.description || '—'}</div>
                    </div>
                    <div className="alert-time">{formatApiDateTime(e.timestamp)}</div>
                  </li>
                ))}
              </ul>
            ) : <EmptyState icon="fa-bell-slash" title="No events recorded" />)}
          </Card>

          <Link className="meter-btn primary" style={{ textAlign: 'center', textDecoration: 'none' }} to={`/consumer-analytics?device=${encodeURIComponent(device.device_id)}`}>
            <i className="fa-solid fa-user-clock" style={{ marginRight: 6 }} />Open in Consumer Analytics
          </Link>
        </div>
      </aside>
    </div>
  );
}
