/**
 * Pure helpers that turn raw telemetry rows (newest first, as the API returns them)
 * into chart series. No values are invented: empty buckets are null (gaps), not 0.
 */
import { parseApiTimestamp, formatApiShort } from './meterStatus';

const HOUR = 3_600_000;

/** Most common non-null flow_unit in rows, and whether more than one unit occurs. */
export function dominantFlowUnit(rows) {
  const counts = new Map();
  for (const r of rows) if (r.flow != null && r.flow_unit) counts.set(r.flow_unit, (counts.get(r.flow_unit) || 0) + 1);
  let best = null;
  let n = 0;
  for (const [u, c] of counts) if (c > n) { best = u; n = c; }
  return { unit: best, mixed: counts.size > 1 };
}

/**
 * Hourly average of `field` from startMs to endMs (IST wall-clock ms). Only rows whose
 * flow_unit equals `unit` are used when unit is given (units are never mixed in one line).
 */
export function hourlyAverage(rows, field, startMs, endMs, unit = undefined) {
  if (startMs == null || endMs == null) return [];
  const first = Math.floor(startMs / HOUR) * HOUR;
  const buckets = new Map();
  for (const r of rows) {
    const v = r[field];
    if (v == null || !Number.isFinite(Number(v))) continue;
    if (unit !== undefined && r.flow_unit !== unit) continue;
    const t = parseApiTimestamp(r.timestamp);
    if (t == null || t < first || t > endMs) continue;
    const k = Math.floor(t / HOUR) * HOUR;
    const b = buckets.get(k) || { s: 0, n: 0 };
    b.s += Number(v); b.n += 1;
    buckets.set(k, b);
  }
  const out = [];
  for (let k = first; k <= endMs; k += HOUR) {
    const b = buckets.get(k);
    out.push({ t: k, label: formatApiShort(new Date(k).toISOString().slice(0, 19)), value: b ? b.s / b.n : null });
  }
  return out;
}

/** Raw series of one field (oldest first) for a single device. */
export function rawSeries(rows, field) {
  return rows
    .filter((r) => r[field] != null && Number.isFinite(Number(r[field])))
    .map((r) => ({ t: parseApiTimestamp(r.timestamp), label: formatApiShort(r.timestamp), value: Number(r[field]) }))
    .filter((p) => p.t != null)
    .sort((a, b) => a.t - b.t);
}

/** Histogram of numeric values into fixed bins [{label, count}]. Values outside go to edge bins. */
export function histogram(values, edges, fmt = (a, b) => `${a}–${b}`) {
  const bins = [];
  for (let i = 0; i < edges.length - 1; i += 1) bins.push({ label: fmt(edges[i], edges[i + 1]), count: 0 });
  for (const raw of values) {
    if (raw == null || !Number.isFinite(Number(raw))) continue;
    const v = Number(raw);
    let idx = edges.findIndex((e, i) => i < edges.length - 1 && v >= e && v < edges[i + 1]);
    if (idx === -1) idx = v < edges[0] ? 0 : bins.length - 1;
    bins[idx].count += 1;
  }
  return bins;
}

/** Count occurrences of a (string) field: [{name, value}] sorted desc; null -> 'Not reported'. */
export function countBy(items, getter) {
  const m = new Map();
  for (const it of items) {
    const k = getter(it) || 'Not reported';
    m.set(k, (m.get(k) || 0) + 1);
  }
  return [...m.entries()].map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value);
}
