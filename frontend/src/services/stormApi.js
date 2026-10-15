/**
 * Storm Energy RTU API — read-only service functions (GET only).
 * Endpoint shapes mirror backend/app/api/*.py. Field names are the API's own
 * (snake_case); pages read them directly, no renaming layer to drift out of sync.
 */
import { apiGet } from './apiClient';

/** { server_time, devices: [ {device_id, imei, name, site_id, ..., latitude, longitude, latest_telemetry|null} ] } */
export function fetchDevicesLatest(signal) {
  return apiGet('/api/devices/latest', { signal });
}

export function fetchDevice(deviceId, signal) {
  return apiGet(`/api/devices/${encodeURIComponent(deviceId)}`, { signal });
}

/**
 * Telemetry across devices (newest first). The API caps `limit` at 5000; callers
 * compare the result length to the limit to detect a truncated (partial) window.
 */
export const TELEMETRY_MAX_LIMIT = 5000;

export function fetchTelemetry({ from, to, deviceId, protocol, limit = TELEMETRY_MAX_LIMIT } = {}, signal) {
  return apiGet('/api/telemetry', {
    params: { device_id: deviceId, from, to, protocol, limit },
    signal,
  });
}

export function fetchDeviceTelemetry(deviceId, { from, to, limit = 2000 } = {}, signal) {
  return apiGet(`/api/telemetry/${encodeURIComponent(deviceId)}`, { params: { from, to, limit }, signal });
}

export function fetchDeviceConfiguration(deviceId, signal) {
  return apiGet(`/api/devices/${encodeURIComponent(deviceId)}/configuration`, { signal });
}

export function fetchDeviceCommands(deviceId, signal) {
  return apiGet(`/api/devices/${encodeURIComponent(deviceId)}/commands`, { signal });
}

export function fetchDeviceEvents(deviceId, signal) {
  return apiGet(`/api/devices/${encodeURIComponent(deviceId)}/events`, { signal });
}

export function fetchRecentEvents(signal) {
  return apiGet('/api/events', { signal });
}

export function fetchHealth(signal) {
  return apiGet('/health', { signal });
}

// ── Protocol Test Log (read-only diagnostics) ────────────────────────────────
export const DIAG_PAGE_SIZES = [50, 100, 250];

/** protocol: 'tcp' | 'mqtt'. filters: { status, device_id, imei, source_ip, topic } */
export function fetchDiagnostics(protocol, { page = 1, pageSize = 50, filters = {} } = {}, signal) {
  return apiGet(`/api/diagnostics/${protocol === 'mqtt' ? 'mqtt' : 'tcp'}`, {
    params: { page, page_size: pageSize, ...filters },
    signal,
  });
}

export function fetchDiagnostic(protocol, id, signal) {
  return apiGet(`/api/diagnostics/${protocol === 'mqtt' ? 'mqtt' : 'tcp'}/${encodeURIComponent(id)}`, { signal });
}

// ── Testing / Protocol Monitor (combined TCP + MQTT, read-only) ─────────────
/** window: today | 1h | 24h | 7d | all */
export function fetchTestingSummary(window = 'today', signal) {
  return apiGet('/api/diagnostics/summary', { params: { window }, signal });
}

export function fetchTestingSources(window = '24h', signal) {
  return apiGet('/api/diagnostics/sources', { params: { window }, signal });
}

/** filters: { protocol, status, device_id, site_id, source_ip, topic, window, from, to } */
export function fetchPackets({ page = 1, pageSize = 50, filters = {} } = {}, signal) {
  return apiGet('/api/diagnostics/packets', { params: { page, page_size: pageSize, ...filters }, signal });
}

export function fetchPacket(id, signal) {
  return apiGet(`/api/diagnostics/packets/${encodeURIComponent(id)}`, { signal });
}

// ── Analytics (read-only, aggregated server-side; consumption in KL) ─────────
/** Total Today (KL): all active meters, last 24 h. */
export function fetchAnalyticsOverview(signal) {
  return apiGet('/api/analytics/overview', { signal });
}

export function fetchAnalyticsDaily(days = 7, signal) {
  return apiGet('/api/analytics/daily', { params: { days }, signal });
}

/** Last 24 h / yesterday / last month for one meter. */
export function fetchDeviceConsumption(deviceId, signal) {
  return apiGet(`/api/analytics/devices/${encodeURIComponent(deviceId)}/consumption`, { signal });
}

/** window: 24h | 7d | 30d (bucketed server-side). */
export function fetchDeviceTrend(deviceId, window = '24h', signal) {
  return apiGet(`/api/analytics/devices/${encodeURIComponent(deviceId)}/trend`, { params: { window }, signal });
}

export function fetchDeviceHistory(deviceId, { page = 1, pageSize = 50, order = 'desc' } = {}, signal) {
  return apiGet(`/api/analytics/devices/${encodeURIComponent(deviceId)}/history`, {
    params: { page, page_size: pageSize, order }, signal,
  });
}

/** period: yesterday | 7d | 30d */
export function fetchHeatmap(period = 'yesterday', signal) {
  return apiGet('/api/analytics/heatmap', { params: { period }, signal });
}
