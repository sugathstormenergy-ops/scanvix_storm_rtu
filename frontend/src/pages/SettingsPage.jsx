/**
 * Settings — platform health, the fixed status rules, and per-browser display preferences.
 * Contains no secrets and no server configuration.
 */
import { useState } from 'react';
import { Card } from '../components/ui/Card';
import { ErrorBanner } from '../components/ui/PageState';
import { StatusPill } from '../components/ui/StatusPill';
import { useAsyncData } from '../hooks/useAsyncData';
import { fetchHealth } from '../services/stormApi';
import { PREF_CHOICES, getPref, setPref } from '../utils/prefs';

/* global __APP_VERSION__ */
const FRONTEND_VERSION = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : 'dev';

function HealthRow({ name, s }) {
  return (
    <tr>
      <td className="meter-id">{name}</td>
      <td><StatusPill status={s?.status} label={s?.status ?? '—'} /></td>
      <td>{s?.details || '—'}</td>
    </tr>
  );
}

function PrefSelect({ name, label, format = (v) => v, onSaved }) {
  const [value, setValue] = useState(() => getPref(name));
  return (
    <label className="kv-item" style={{ display: 'block' }}>
      <div className="kv-label">{label}</div>
      <select className="meter-control meter-select" style={{ marginTop: 4, width: '100%' }} value={value}
        onChange={(e) => {
          const raw = e.target.value;
          const v = typeof PREF_CHOICES[name][0] === 'number' ? Number(raw) : raw;
          setValue(v);
          onSaved(setPref(name, v));
        }}>
        {PREF_CHOICES[name].map((c) => <option key={c} value={c}>{format(c)}</option>)}
      </select>
    </label>
  );
}

export default function SettingsPage() {
  const health = useAsyncData((signal) => fetchHealth(signal), []);
  const [saved, setSaved] = useState(null);
  const h = health.data;

  return (
    <div className="content" data-testid="page-settings">
      <Card icon="fa-heart-pulse" title="Platform health" className="auto"
        action={<button type="button" className="meter-btn" onClick={health.reload}><i className="fa-solid fa-rotate" style={{ marginRight: 4 }} />Check</button>}>
        {health.loading && <div className="skeleton" style={{ height: 90, borderRadius: 10 }} />}
        {health.error && <ErrorBanner message={`Health check failed: ${health.error.message}`} onRetry={health.reload} />}
        {h && (
          <div className="table-scroll">
            <table className="meter-table" data-testid="health-table">
              <thead><tr><th>Component</th><th>Status</th><th>Details</th></tr></thead>
              <tbody>
                <HealthRow name="Overall" s={{ status: h.status, details: `API version ${h.version} · checked ${h.timestamp}` }} />
                <HealthRow name="Database" s={h.database} />
                <HealthRow name="MQTT consumer" s={h.mqtt} />
                <HealthRow name="TCP listener" s={h.tcp} />
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card icon="fa-traffic-light" title="Meter status rules (fixed)" className="auto">
        <div className="kv-grid" data-testid="status-rules">
          <div className="kv-item"><div className="kv-label"><StatusPill status="online" /></div><div className="kv-value">Active and last seen within the last 24 hours</div></div>
          <div className="kv-item"><div className="kv-label"><StatusPill status="delayed" /></div><div className="kv-value">Active and last seen more than 24 hours ago</div></div>
          <div className="kv-item"><div className="kv-label"><StatusPill status="offline" /></div><div className="kv-value">Active and has never communicated</div></div>
          <div className="kv-item"><div className="kv-label"><StatusPill status="inactive" /></div><div className="kv-value">Disabled in the registry; counted only in Total Meters</div></div>
        </div>
        <p className="page-note" style={{ marginTop: 8 }}>Ages are measured against the server clock returned with the data, not this computer&apos;s clock.</p>
      </Card>

      <Card icon="fa-display" title="Display preferences (this browser only)" className="auto">
        <div className="kv-grid">
          <PrefSelect name="refreshSeconds" label="Auto-refresh interval" format={(v) => (v < 60 ? `${v} seconds` : `${v / 60} minute${v === 60 ? '' : 's'}`)} onSaved={setSaved} />
          <PrefSelect name="basemap" label="Default map" format={(v) => (v === 'street' ? 'Street' : 'Satellite')} onSaved={setSaved} />
          <PrefSelect name="pageSize" label="Overview rows per page" onSaved={setSaved} />
        </div>
        {saved === true && <p className="page-note" style={{ marginTop: 8 }}>Saved. Changes apply when a page is reopened or the browser is reloaded.</p>}
        {saved === false && <p className="page-note" style={{ marginTop: 8 }}>This browser does not allow saving preferences; defaults are used.</p>}
      </Card>

      <Card icon="fa-circle-info" title="About" className="auto">
        <div className="kv-grid">
          <div className="kv-item"><div className="kv-label">Application</div><div className="kv-value">Storm Energy RTU</div></div>
          <div className="kv-item"><div className="kv-label">Frontend version</div><div className="kv-value">{FRONTEND_VERSION}</div></div>
          <div className="kv-item"><div className="kv-label">API version</div><div className="kv-value">{h?.version ?? '—'}</div></div>
          <div className="kv-item"><div className="kv-label">Access</div><div className="kv-value">Read-only. Write actions require authentication (not yet enabled).</div></div>
        </div>
      </Card>
    </div>
  );
}
