/**
 * Maintenance — READ-ONLY.
 * Shows device information, stored configuration, command history and events.
 * Configuration changes, commands and device edits exist in the API but are NOT callable
 * from this UI: they are shown disabled with "Requires authentication (not yet enabled)".
 */
import { useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { useStormData } from '../store/StormDataContext';
import { Card } from '../components/ui/Card';
import { ErrorBanner, PageError, PageLoading } from '../components/ui/PageState';
import { StatusPill } from '../components/ui/StatusPill';
import { AuthRequiredAction, EmptyState } from '../components/ui/EmptyState';
import { useAsyncData } from '../hooks/useAsyncData';
import { fetchDeviceCommands, fetchDeviceConfiguration, fetchDeviceEvents } from '../services/stormApi';
import {
  displayName, formatAge, formatApiDateTime, hasValidLocation, meterStatus, parseApiTimestamp,
} from '../utils/meterStatus';

const TABS = [
  { key: 'info', label: 'Device information', icon: 'fa-circle-info' },
  { key: 'config', label: 'Configuration', icon: 'fa-sliders' },
  { key: 'commands', label: 'Command history', icon: 'fa-terminal' },
  { key: 'events', label: 'Events', icon: 'fa-bell' },
];

function KV({ label, value }) {
  const empty = value == null || value === '';
  return (
    <div className="kv-item">
      <div className="kv-label">{label}</div>
      <div className={`kv-value${empty ? ' muted' : ''}`}>{empty ? '—' : value}</div>
    </div>
  );
}

function DeviceInfo({ device, nowMs }) {
  return (
    <div className="stack">
      <div className="kv-grid" data-testid="device-info">
        <KV label="Device ID" value={device.device_id} />
        <KV label="Name" value={device.name} />
        <KV label="IMEI" value={device.imei} />
        <KV label="Site" value={device.site_id} />
        <KV label="Status" value={<StatusPill status={meterStatus(device, nowMs)} />} />
        <KV label="Registry state" value={device.is_active ? 'Active' : 'Inactive'} />
        <KV label="Communication mode" value={device.communication_mode} />
        <KV label="Firmware" value={device.firmware_version} />
        <KV label="Last seen" value={device.last_seen_at ? `${formatApiDateTime(device.last_seen_at)} (${formatAge(device.last_seen_at, nowMs)})` : 'Never'} />
        <KV label="Last IP address" value={device.last_ip_address} />
        <KV label="Location" value={hasValidLocation(device) ? `${Number(device.latitude).toFixed(6)}, ${Number(device.longitude).toFixed(6)}` : 'No location assigned'} />
        <KV label="Registered" value={formatApiDateTime(device.created_at)} />
      </div>
      <AuthRequiredAction icon="fa-pen" label="Edit device" />
    </div>
  );
}

function ConfigurationTab({ deviceId }) {
  const res = useAsyncData((signal) => fetchDeviceConfiguration(deviceId, signal), [deviceId]);
  if (res.loading) return <div className="skeleton" style={{ height: 120, borderRadius: 10 }} />;
  if (res.error?.status === 404) {
    return (
      <div className="stack">
        <EmptyState icon="fa-sliders" title="No configuration stored for this device" testId="config-empty" />
        <AuthRequiredAction icon="fa-pen" label="Edit configuration" />
      </div>
    );
  }
  if (res.error) return <ErrorBanner message={res.error.message} onRetry={res.reload} />;
  const c = res.data;
  return (
    <div className="stack">
      <div className="kv-grid" data-testid="config-values">
        <KV label="Communication mode" value={c.communication_mode} />
        <KV label="MQTT broker" value={c.mqtt_broker} />
        <KV label="MQTT port" value={c.mqtt_port} />
        <KV label="MQTT TLS" value={c.mqtt_tls_enabled ? 'Enabled' : 'Disabled'} />
        <KV label="TCP host" value={c.tcp_host} />
        <KV label="TCP port" value={c.tcp_port} />
        <KV label="Reporting interval" value={c.reporting_interval} />
        <KV label="APN" value={c.apn} />
        <KV label="Modbus slave ID" value={c.slave_id} />
        <KV label="Baud rate" value={c.baud_rate} />
        <KV label="Parity" value={c.parity} />
        <KV label="Range" value={c.range_value} />
        <KV label="Updated" value={formatApiDateTime(c.updated_at)} />
      </div>
      <AuthRequiredAction icon="fa-pen" label="Edit configuration" />
    </div>
  );
}

function CommandsTab({ deviceId }) {
  const res = useAsyncData((signal) => fetchDeviceCommands(deviceId, signal), [deviceId]);
  return (
    <div className="stack">
      <AuthRequiredAction icon="fa-paper-plane" label="Send command" />
      {res.loading && <div className="skeleton" style={{ height: 80, borderRadius: 10 }} />}
      {res.error && <ErrorBanner message={res.error.message} onRetry={res.reload} />}
      {res.data && (res.data.length ? (
        <div className="table-scroll">
          <table className="meter-table" data-testid="commands-table">
            <thead><tr><th>Created</th><th>Command</th><th>Protocol</th><th>Status</th><th>Sent</th><th>Payload</th><th>Response</th></tr></thead>
            <tbody>
              {res.data.map((c) => (
                <tr key={c.id}>
                  <td>{formatApiDateTime(c.created_at)}</td><td className="meter-id">{c.command}</td><td>{c.protocol}</td>
                  <td>{c.status}</td><td>{formatApiDateTime(c.sent_at)}</td>
                  <td style={{ maxWidth: 220, overflowWrap: 'anywhere' }}>{c.payload || '—'}</td>
                  <td style={{ maxWidth: 220, overflowWrap: 'anywhere' }}>{c.response || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <EmptyState icon="fa-terminal" title="No commands have been sent to this device" />)}
    </div>
  );
}

function EventsTab({ deviceId }) {
  const res = useAsyncData((signal) => fetchDeviceEvents(deviceId, signal), [deviceId]);
  if (res.loading) return <div className="skeleton" style={{ height: 80, borderRadius: 10 }} />;
  if (res.error) return <ErrorBanner message={res.error.message} onRetry={res.reload} />;
  if (!res.data.length) return <EmptyState icon="fa-bell-slash" title="No events recorded for this device" />;
  return (
    <div className="table-scroll">
      <table className="meter-table" data-testid="events-table">
        <thead><tr><th>Time</th><th>Severity</th><th>Type</th><th>Protocol</th><th>Description</th></tr></thead>
        <tbody>
          {res.data.map((e) => (
            <tr key={e.id}>
              <td>{formatApiDateTime(e.timestamp)}</td><td>{e.severity}</td><td className="meter-id">{e.event_type}</td>
              <td>{e.protocol || '—'}</td><td>{e.description || '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function MaintenancePage() {
  const { devices, serverTime, loading, error, hasData, refresh } = useStormData();
  const { deviceId } = useParams();
  const navigate = useNavigate();
  const [query, setQuery] = useState('');
  const [tab, setTab] = useState('info');
  const nowMs = parseApiTimestamp(serverTime);

  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    return devices
      .filter((d) => !q || [d.device_id, d.name, d.imei, d.site_id].some((v) => v && String(v).toLowerCase().includes(q)))
      .sort((a, b) => displayName(a).localeCompare(displayName(b)));
  }, [devices, query]);
  const device = deviceId ? devices.find((d) => d.device_id === deviceId) : null;

  if (loading && !hasData) return <PageLoading label="Loading meters…" />;
  if (!hasData && error) return <div className="content"><PageError title="Cannot load meters" message={error.message} onRetry={refresh} /></div>;

  return (
    <div className="content" data-testid="page-maintenance">
      {error && <ErrorBanner message={`Refresh failed: ${error.message}. Showing the last successful data.`} onRetry={refresh} />}
      <div className="page-note" data-testid="readonly-note">
        <i className="fa-solid fa-lock" />Read-only view. Configuration changes, commands and device edits require authentication, which is not yet enabled.
      </div>

      <div className="split-layout">
        <Card icon="fa-list" title={`Meters (${devices.length})`} className="auto">
          <input className="meter-control meter-search" style={{ width: '100%', marginBottom: 8 }} type="search"
            placeholder="Search…" aria-label="Search meters" value={query} onChange={(e) => setQuery(e.target.value)} />
          {devices.length === 0 ? <EmptyState icon="fa-microchip" title="No meters registered" /> : (
            <nav className="device-list" aria-label="Meters">
              {list.map((d) => (
                <Link key={d.device_id} to={`/maintenance/${encodeURIComponent(d.device_id)}`}
                  className={`device-list-item${d.device_id === deviceId ? ' active' : ''}`}>
                  <div style={{ minWidth: 0 }}>
                    <div className="dl-name">{displayName(d)}</div>
                    <div className="dl-sub">{d.name ? `${d.device_id} · ` : ''}{d.site_id || 'No site'}</div>
                  </div>
                  <StatusPill status={meterStatus(d, nowMs)} />
                </Link>
              ))}
              {list.length === 0 && <div className="page-note">No meters match.</div>}
            </nav>
          )}
        </Card>

        <div className="stack">
          {!deviceId && <Card className="auto"><EmptyState icon="fa-hand-pointer" title="Select a meter" testId="maintenance-select">Choose a meter on the left to view its configuration, command history and events.</EmptyState></Card>}
          {deviceId && !device && (
            <Card className="auto">
              <EmptyState icon="fa-circle-question" title="Meter not found" testId="maintenance-not-found">
                No meter with ID “{deviceId}” is registered. <button type="button" className="meter-link" onClick={() => navigate('/maintenance')}>Back to the list</button>
              </EmptyState>
            </Card>
          )}
          {device && (
            <Card icon="fa-microchip" title={displayName(device)} className="auto"
              action={<StatusPill status={meterStatus(device, nowMs)} />}>
              <div className="tab-row" role="tablist" style={{ marginBottom: 12 }}>
                {TABS.map((t) => (
                  <button key={t.key} type="button" role="tab" aria-selected={tab === t.key}
                    className={`tab-btn${tab === t.key ? ' active' : ''}`} onClick={() => setTab(t.key)}>
                    <i className={`fa-solid ${t.icon}`} style={{ marginRight: 5 }} />{t.label}
                  </button>
                ))}
              </div>
              {tab === 'info' && <DeviceInfo device={device} nowMs={nowMs} />}
              {tab === 'config' && <ConfigurationTab deviceId={device.device_id} />}
              {tab === 'commands' && <CommandsTab deviceId={device.device_id} />}
              {tab === 'events' && <EventsTab deviceId={device.device_id} />}
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
