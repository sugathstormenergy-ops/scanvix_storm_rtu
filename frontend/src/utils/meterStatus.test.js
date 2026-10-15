import { describe, expect, it } from 'vitest';
import {
  DELAY_THRESHOLD_MS, STATUS, apiDateKey, computeKpis, hasValidLocation, meterStatus,
  parseApiTimestamp, totalUnitFromFlowUnit, fmtNum, formatAge,
} from './meterStatus';

const NOW = '2026-09-25T12:00:00';
const nowMs = parseApiTimestamp(NOW);
const dev = (over) => ({ device_id: 'X', is_active: true, last_seen_at: null, latest_telemetry: null, ...over });

describe('parseApiTimestamp', () => {
  it('treats naive API timestamps as wall-clock (browser timezone independent)', () => {
    expect(parseApiTimestamp('2026-09-25T12:00:00')).toBe(Date.UTC(2026, 8, 25, 12, 0, 0));
    expect(parseApiTimestamp('2026-09-25T12:00:00.123456')).toBe(Date.UTC(2026, 8, 25, 12, 0, 0, 123));
    expect(parseApiTimestamp('2026-09-25 12:00')).toBe(Date.UTC(2026, 8, 25, 12, 0, 0));
  });
  it('converts offset-aware timestamps to the IST wall-clock convention', () => {
    expect(parseApiTimestamp('2026-09-25T06:30:00Z')).toBe(Date.UTC(2026, 8, 25, 12, 0, 0));
    expect(parseApiTimestamp('2026-09-25T12:00:00+05:30')).toBe(Date.UTC(2026, 8, 25, 12, 0, 0));
  });
  it('returns null (not 0 / not now) for missing or bad values', () => {
    for (const v of [null, undefined, '', 'garbage']) expect(parseApiTimestamp(v)).toBeNull();
  });
});

describe('meterStatus - approved rules', () => {
  it('online when last seen within 24 h', () => {
    expect(meterStatus(dev({ last_seen_at: '2026-09-25T11:59:00' }), nowMs)).toBe(STATUS.ONLINE);
  });
  it('EXACTLY 24 h is still online (<= 24h)', () => {
    expect(meterStatus(dev({ last_seen_at: '2026-09-24T12:00:00' }), nowMs)).toBe(STATUS.ONLINE);
  });
  it('24 h + 1 s is delayed (> 24h)', () => {
    expect(meterStatus(dev({ last_seen_at: '2026-09-24T11:59:59' }), nowMs)).toBe(STATUS.DELAYED);
  });
  it('threshold constant is exactly 24 hours', () => {
    expect(DELAY_THRESHOLD_MS).toBe(86_400_000);
  });
  it('exactly 48 h is still delayed; 48 h + 1 s and months of silence are stale', () => {
    expect(meterStatus(dev({ last_seen_at: '2026-09-23T12:00:00' }), nowMs)).toBe(STATUS.DELAYED);
    expect(meterStatus(dev({ last_seen_at: '2026-09-23T11:59:59' }), nowMs)).toBe(STATUS.STALE);
    expect(meterStatus(dev({ last_seen_at: '2026-01-01T00:00:00' }), nowMs)).toBe(STATUS.STALE);
  });
  it('offline = active and never communicated', () => {
    expect(meterStatus(dev({ last_seen_at: null }), nowMs)).toBe(STATUS.OFFLINE);
  });
  it('inactive regardless of last_seen_at', () => {
    expect(meterStatus(dev({ is_active: false, last_seen_at: '2026-09-25T11:59:00' }), nowMs)).toBe(STATUS.INACTIVE);
    expect(meterStatus(dev({ is_active: false, last_seen_at: null }), nowMs)).toBe(STATUS.INACTIVE);
  });
  it('future timestamps (clock drift) count as online, not delayed', () => {
    expect(meterStatus(dev({ last_seen_at: '2026-09-25T12:05:00' }), nowMs)).toBe(STATUS.ONLINE);
  });
});

describe('computeKpis', () => {
  const devices = [
    dev({ device_id: 'A', last_seen_at: '2026-09-25T11:00:00', latest_telemetry: { timestamp: '2026-09-25T11:00:00', total_today: 100.5, flow_unit: 'm3/h' } }),
    dev({ device_id: 'B', last_seen_at: '2026-09-24T12:00:00', latest_telemetry: { timestamp: '2026-09-24T12:00:00', total_today: 999, flow_unit: 'm3/h' } }), // online, but reading is YESTERDAY
    dev({ device_id: 'C', last_seen_at: '2026-09-20T09:00:00', latest_telemetry: { timestamp: '2026-09-20T09:00:00', total_today: 5, flow_unit: 'm3/h' } }),  // delayed
    dev({ device_id: 'D', last_seen_at: null }),                                                                                                                // offline
    dev({ device_id: 'E', is_active: false, last_seen_at: '2026-09-25T11:30:00', latest_telemetry: { timestamp: '2026-09-25T11:30:00', total_today: 20, flow_unit: 'm3/h' } }),
  ];
  const k = computeKpis(devices, NOW);
  it('counts follow the approved rules; inactive only in total', () => {
    expect(k.total).toBe(5);
    expect(k.active).toBe(4);
    expect(k.online).toBe(2);
    expect(k.delayed).toBe(0);
    expect(k.stale).toBe(1);
    expect(k.offline).toBe(1);
    expect(k.inactive).toBe(1);
    expect(k.online + k.delayed + k.stale + k.offline).toBe(k.active);
  });
  it('no devices -> zero counts', () => {
    const e = computeKpis([], NOW);
    expect(e.total).toBe(0);
    expect(e.active + e.online + e.delayed + e.stale + e.offline).toBe(0);
  });
  it('missing server_time -> statuses cannot be aged: never-seen = offline, others not online', () => {
    const e = computeKpis([dev({ last_seen_at: null })], null);
    expect(e.offline).toBe(1);
  });
});

describe('location', () => {
  it('accepts real coordinates only', () => {
    expect(hasValidLocation({ latitude: 17.385, longitude: 78.4867 })).toBe(true);
    expect(hasValidLocation({ latitude: '17.385', longitude: '78.4867' })).toBe(true);
  });
  it('rejects NULL, half-set, 0,0, out of range and non-numeric', () => {
    for (const d of [
      { latitude: null, longitude: null }, { latitude: 17.3, longitude: null }, { latitude: null, longitude: 78.4 },
      { latitude: 0, longitude: 0 }, { latitude: 91, longitude: 10 }, { latitude: 10, longitude: 181 },
      { latitude: 'abc', longitude: 1 }, { latitude: '', longitude: '' }, {},
    ]) expect(hasValidLocation(d)).toBe(false);
  });
  it('a meter on the equator or prime meridian (but not both 0) is valid', () => {
    expect(hasValidLocation({ latitude: 0, longitude: 32.5 })).toBe(true);
    expect(hasValidLocation({ latitude: 51.5, longitude: 0 })).toBe(true);
  });
});

describe('formatting never fabricates zero', () => {
  it('fmtNum', () => {
    expect(fmtNum(null)).toBe('—');
    expect(fmtNum(undefined)).toBe('—');
    expect(fmtNum('x')).toBe('—');
    expect(fmtNum(0)).toBe('0.00');
  });
  it('formatAge', () => {
    expect(formatAge(null, nowMs)).toBe('Never');
    expect(formatAge('2026-09-25T11:55:00', nowMs)).toBe('5 min ago');
    expect(formatAge('2026-09-23T12:00:00', nowMs)).toBe('2 d ago');
  });
  it('apiDateKey + unit derivation', () => {
    expect(apiDateKey('2026-09-25T23:59:59')).toBe('2026-09-25');
    expect(totalUnitFromFlowUnit('m3/h')).toBe('m3');
    expect(totalUnitFromFlowUnit('L / min')).toBe('L');
    expect(totalUnitFromFlowUnit('m3')).toBeNull();
  });
});
