/** Test fixtures shaped exactly like the Storm API responses. */
export const SERVER_TIME = '2026-09-25T12:00:00';

const tele = (over) => ({
  id: 1, device_id: 'X', site_id: null, timestamp: '2026-09-25T11:00:00', received_at: '2026-09-25T11:00:01',
  protocol: 'MQTT', flow: 12.5, flow_unit: 'm3/h', total_today: 100, total_yesterday: 240, sensor_type: 'EMF',
  signal_dbm: -71, battery: 3.6, firmware_version: '1.2', read01: 'A1', read02: null, read03: null, read04: null,
  read05: null, pressure: 2.1, is_historical: false, ...over,
});

const dev = (over) => ({
  device_id: 'X', imei: '860000000000000', site_id: 'SITE-A', firmware_version: '1.2', communication_mode: 'MQTT',
  is_active: true, last_seen_at: null, last_ip_address: null, created_at: '2026-09-01T10:00:00',
  name: null, latitude: null, longitude: null, latest_telemetry: null, ...over,
});

export const DEVICES_LATEST = {
  server_time: SERVER_TIME,
  devices: [
    dev({ device_id: 'RTU-001', name: 'Pump House 1', last_seen_at: '2026-09-25T11:00:00', latitude: 17.385, longitude: 78.4867,
      latest_telemetry: tele({ id: 11, device_id: 'RTU-001', site_id: 'SITE-A', total_today: 100.5 }) }),
    dev({ device_id: 'RTU-002', last_seen_at: '2026-09-24T12:00:00',
      latest_telemetry: tele({ id: 12, device_id: 'RTU-002', timestamp: '2026-09-24T12:00:00', total_today: 999 }) }),
    dev({ device_id: 'RTU-003', site_id: 'SITE-B', last_seen_at: '2026-09-20T09:00:00',
      latest_telemetry: tele({ id: 13, device_id: 'RTU-003', timestamp: '2026-09-20T09:00:00', protocol: 'TCP' }) }),
    dev({ device_id: 'RTU-004', site_id: 'SITE-B' }),
    dev({ device_id: 'RTU-005', is_active: false, last_seen_at: '2026-09-25T11:30:00', latitude: 0, longitude: 0,
      latest_telemetry: tele({ id: 15, device_id: 'RTU-005', timestamp: '2026-09-25T11:30:00', total_today: 20 }) }),
  ],
};

export const TELEMETRY = [
  tele({ id: 21, device_id: 'RTU-001', timestamp: '2026-09-25T11:00:00', flow: 10 }),
  tele({ id: 20, device_id: 'RTU-001', timestamp: '2026-09-25T10:00:00', flow: 14 }),
];

export const ANALYTICS_OVERVIEW = {
  server_time: SERVER_TIME, window_from: '2026-09-24T12:00:00', window_to: SERVER_TIME, total_kl: 1234.5, meters_counted: 2, meters_excluded: 0,
};
export const ANALYTICS_DAILY = {
  server_time: SERVER_TIME,
  days: [
    { date: '2026-09-23', kl: 40.5, meters: 2, excluded_meters: 0 },
    { date: '2026-09-24', kl: null, meters: 0, excluded_meters: 0 },
    { date: '2026-09-25', kl: 12, meters: 1, excluded_meters: 0 },
  ],
};
const period = (over) => ({
  key: 'last_24h', label: 'Last 24 hours', window_from: '2026-09-24T12:00:00', window_to: SERVER_TIME, days: 1,
  consumption_kl: 10, consumption_raw: 10, total_unit: 'm3', avg_per_day_kl: 10, flow_avg: 5, flow_max: 9, flow_min: 1, readings: 20,
  unit_convertible: true, ...over,
});
export const CONSUMPTION_RTU001 = {
  device_id: 'RTU-001', server_time: SERVER_TIME, flow_unit: 'm3/h',
  periods: [
    period({}),
    period({ key: 'yesterday', label: 'Yesterday', consumption_kl: 24, flow_avg: 6, flow_max: 11, flow_min: 2 }),
    period({ key: 'last_month', label: 'Last month (Aug 2026)', days: 31, consumption_kl: 620, flow_avg: 7, flow_max: 15, flow_min: 0.5, readings: 900 }),
  ],
};
export const TREND_RTU001 = {
  device_id: 'RTU-001', window: '24h', bucket_minutes: 60, flow_unit: 'm3/h',
  points: [{ t: '2026-09-25T09:00:00', avg: 8, min: 4, max: 12, n: 6 }, { t: '2026-09-25T10:00:00', avg: 10, min: 6, max: 14, n: 6 }],
};
export const HISTORY_RTU001 = {
  device_id: 'RTU-001', total: 60, page: 1, page_size: 50,
  items: [
    tele({ id: 21, device_id: 'RTU-001', timestamp: '2026-09-25T11:00:00', flow: 10, battery: null }),
    tele({ id: 20, device_id: 'RTU-001', timestamp: '2026-09-25T10:00:00', flow: 14 }),
  ],
};

export const HEALTH = {
  status: 'ok', timestamp: '2026-09-25T06:30:00Z', version: '1.0.0',
  database: { status: 'ok', details: 'SQL Server reachable' },
  mqtt: { status: 'ok', details: 'Broker connected' },
  tcp: { status: 'disabled', details: 'TCP listener runs in a separate process/container' },
};

export const CONFIG = {
  device_id: 'RTU-001', communication_mode: 'MQTT', mqtt_broker: 'mqtt.example', mqtt_port: 8883, mqtt_tls_enabled: true,
  tcp_host: null, tcp_port: null, reporting_interval: 900, apn: 'internet', slave_id: 1, baud_rate: 9600, parity: 'N',
  range_value: 100, updated_at: '2026-09-20T10:00:00',
};

/**
 * Installs a fetch stub routing by path. `routes` maps a path (no query) to a body,
 * a function(url) -> body, or { httpStatus, body }. Unknown paths -> 404. Every call is recorded.
 */
export function stubApi(routes) {
  const calls = [];
  const fetchMock = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method || 'GET' });
    const path = String(url).split('?')[0];
    let r = routes[path];
    if (typeof r === 'function') r = r(String(url));
    if (r === undefined) r = { httpStatus: 404, body: { detail: 'Not Found' } };
    if (r instanceof Error) throw r;
    const { httpStatus = 200, body } = r && Object.prototype.hasOwnProperty.call(r, 'httpStatus') ? r : { body: r };
    return new Response(JSON.stringify(body), { status: httpStatus, headers: { 'Content-Type': 'application/json' } });
  };
  globalThis.fetch = fetchMock;
  return calls;
}

export function defaultRoutes(over = {}) {
  return {
    '/api/devices/latest': DEVICES_LATEST,
    '/api/telemetry': TELEMETRY,
    '/api/telemetry/RTU-001': TELEMETRY,
    '/api/devices/RTU-001/events': [],
    '/api/devices/RTU-001/configuration': CONFIG,
    '/api/devices/RTU-001/commands': [],
    '/api/analytics/overview': ANALYTICS_OVERVIEW,
    '/api/analytics/daily': ANALYTICS_DAILY,
    '/api/analytics/devices/RTU-001/consumption': CONSUMPTION_RTU001,
    '/api/analytics/devices/RTU-001/trend': TREND_RTU001,
    '/api/analytics/devices/RTU-001/history': HISTORY_RTU001,
    '/api/analytics/heatmap': { period: 'yesterday', window_from: '', window_to: '', points: [], located_meters: 1, without_consumption: 1 },
    '/health': HEALTH,
    ...over,
  };
}
