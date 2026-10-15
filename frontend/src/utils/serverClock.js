/**
 * Server-clock display for the Protocol Test Log.
 * The API returns naive IST timestamps; they are parsed as wall-clock values (never via the
 * browser timezone) and advanced with a monotonic clock between polls, so the displayed
 * SERVER TIME is always derived from the server, not from the browser's clock or timezone.
 */
import { parseApiTimestamp } from './meterStatus';

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** IST wall-clock ms -> 'DD-Mon-YYYY HH:MM:SS IST' (UTC getters = no browser tz involvement). */
export function formatIstMs(ms) {
  if (ms == null || !Number.isFinite(ms)) return '—';
  const d = new Date(ms);
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getUTCDate())}-${MONTHS[d.getUTCMonth()]}-${d.getUTCFullYear()} `
    + `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())} IST`;
}

/** Anchor = { serverMs, monoMs } captured when a response arrives. */
export function makeAnchor(serverTime, monoNow) {
  const serverMs = parseApiTimestamp(serverTime);
  return serverMs == null ? null : { serverMs, monoMs: monoNow };
}

export function serverNowFromAnchor(anchor, monoNow) {
  if (!anchor) return null;
  return anchor.serverMs + Math.max(0, monoNow - anchor.monoMs);
}
