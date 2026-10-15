/**
 * Storm Energy RTU — meter status and KPI rules (single source of truth).
 *
 * STATUS RULES (approved):
 *   inactive : is_active === false                       (counts only toward Total Meters)
 *   online   : active AND last_seen_at within the last 24 hours   (age <= 24h)
 *   delayed  : active AND last seen more than 24 h but at most 48 h ago  (24h < age <= 48h)
 *   stale    : active AND last seen more than 48 hours ago        (age > 48h)
 *   offline  : active AND last_seen_at is null (never communicated - never counted as online)
 *
 * TIME BASE
 *   The API stores and returns naive IST timestamps (no UTC offset). Ages are therefore
 *   computed as  server_time - last_seen_at, where server_time comes from the SAME API
 *   response (GET /api/devices/latest). Both are parsed with identical rules, so the
 *   browser's timezone and clock never influence a status.
 */

export const DELAY_THRESHOLD_MS = 24 * 60 * 60 * 1000;
export const STALE_THRESHOLD_MS = 48 * 60 * 60 * 1000;

export const STATUS = Object.freeze({
  ONLINE: 'online',
  DELAYED: 'delayed',
  STALE: 'stale',
  OFFLINE: 'offline',
  INACTIVE: 'inactive',
});

export const STATUS_LABEL = Object.freeze({
  online: 'Online',
  delayed: 'Delayed',
  stale: 'Stale',
  offline: 'Offline',
  inactive: 'Inactive',
});

const NAIVE_RE = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?$/;
const IST_OFFSET_MS = (5 * 60 + 30) * 60 * 1000;

/**
 * Parse an API timestamp into a comparable "IST wall-clock" millisecond value.
 *  - naive 'YYYY-MM-DDTHH:MM[:SS[.ffffff]]' (the API's convention) -> components taken as-is
 *  - offset-aware ISO strings are converted to IST wall-clock so both kinds compare correctly
 * Returns null for null/empty/unparseable input (never 0, never "now").
 */
export function parseApiTimestamp(value) {
  if (value == null || value === '') return null;
  const s = String(value).trim();
  const m = NAIVE_RE.exec(s);
  if (m) {
    const ms = m[7] ? Math.floor(Number(m[7].padEnd(6, '0')) / 1000) : 0;
    return Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5], m[6] ? +m[6] : 0, ms);
  }
  const abs = Date.parse(s);
  if (Number.isNaN(abs)) return null;
  return abs + IST_OFFSET_MS;
}

/** 'YYYY-MM-DD' calendar date (IST convention) of an API timestamp, or null. */
export function apiDateKey(value) {
  const t = parseApiTimestamp(value);
  if (t == null) return null;
  return new Date(t).toISOString().slice(0, 10);
}

/** Age in ms of `value` relative to `serverNowMs`, or null when unknown. */
export function ageMs(value, serverNowMs) {
  const t = parseApiTimestamp(value);
  if (t == null || serverNowMs == null) return null;
  return serverNowMs - t;
}

export function meterStatus(device, serverNowMs) {
  if (!device || device.is_active === false) return STATUS.INACTIVE;
  const age = ageMs(device.last_seen_at, serverNowMs);
  if (age == null) return STATUS.OFFLINE;
  if (age <= DELAY_THRESHOLD_MS) return STATUS.ONLINE;
  return age <= STALE_THRESHOLD_MS ? STATUS.DELAYED : STATUS.STALE;
}

/** Total unit derived from the flow unit: 'm3/h' -> 'm3'. null when not derivable. */
export function totalUnitFromFlowUnit(flowUnit) {
  if (!flowUnit) return null;
  const m = /^\s*(.+?)\s*\/\s*(h|hr|hrs|hour|min|mins|minute|s|sec|second|d|day)\s*$/i.exec(String(flowUnit));
  return m ? m[1] : null;
}

/** Valid coordinates: both present, numeric, in range, and not (0,0). */
export function hasValidLocation(device) {
  if (!device) return false;
  const { latitude: lat, longitude: lng } = device;
  if (lat == null || lng == null || lat === '' || lng === '') return false;
  const la = Number(lat);
  const lo = Number(lng);
  if (!Number.isFinite(la) || !Number.isFinite(lo)) return false;
  if (la < -90 || la > 90 || lo < -180 || lo > 180) return false;
  if (la === 0 && lo === 0) return false;
  return true;
}

export function displayName(device) {
  return (device && (device.name || device.device_id)) || '—';
}

/**
 * Fleet KPIs from the registry snapshot. Every value is derived from API data; the status
 * split uses the SERVER time of the same response. "Total Today (KL)" is NOT computed here:
 * the backend aggregates it (GET /api/analytics/overview) so units are converted safely.
 */
export function computeKpis(devices, serverTime) {
  const list = Array.isArray(devices) ? devices : [];
  const nowMs = parseApiTimestamp(serverTime);
  const counts = { total: list.length, active: 0, online: 0, delayed: 0, stale: 0, offline: 0, inactive: 0 };
  for (const d of list) {
    counts[meterStatus(d, nowMs)] += 1;
    if (d.is_active !== false) counts.active += 1;
  }
  return { ...counts, serverNowMs: nowMs, todayKey: apiDateKey(serverTime) };
}

/** Human-readable age, e.g. "5 min ago", "3 h ago", "2 d ago"; "Never" when null. */
export function formatAge(value, serverNowMs) {
  const a = ageMs(value, serverNowMs);
  if (a == null) return 'Never';
  if (a < 0) return 'just now';
  const min = Math.floor(a / 60000);
  if (min < 1) return 'just now';
  if (min < 60) return `${min} min ago`;
  const h = Math.floor(min / 60);
  if (h < 48) return `${h} h ago`;
  return `${Math.floor(h / 24)} d ago`;
}

/** 'DD-MM-YYYY HH:MM' from an API timestamp (no timezone conversion), '—' when null. */
export function formatApiDateTime(value) {
  const t = parseApiTimestamp(value);
  if (t == null) return '—';
  const d = new Date(t);
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getUTCDate())}-${p(d.getUTCMonth() + 1)}-${d.getUTCFullYear()} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
}

/** Number formatting: null/undefined/NaN -> '—' (never a fabricated 0). */
export function fmtNum(value, decimals = 2) {
  if (value == null || value === '' || !Number.isFinite(Number(value))) return '—';
  return Number(value).toLocaleString('en-IN', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

export function fmtInt(value) {
  if (value == null || !Number.isFinite(Number(value))) return '—';
  return Number(value).toLocaleString('en-IN', { maximumFractionDigits: 0 });
}

/**
 * Inverse of parseApiTimestamp for naive values: IST wall-clock ms -> 'YYYY-MM-DDTHH:MM:SS'.
 * Used to build `from`/`to` query parameters relative to the API's server_time, so query
 * windows use the server's clock and time convention rather than the browser's.
 */
export function toApiNaive(ms) {
  if (ms == null || !Number.isFinite(ms)) return null;
  return new Date(ms).toISOString().slice(0, 19);
}

/** 'DD-MM HH:MM' short label for chart axes. */
export function formatApiShort(value) {
  const t = parseApiTimestamp(value);
  if (t == null) return '—';
  const d = new Date(t);
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getUTCDate())}-${p(d.getUTCMonth() + 1)} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
}
