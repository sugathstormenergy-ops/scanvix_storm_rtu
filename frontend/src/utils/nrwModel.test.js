import { describe, expect, it } from 'vitest';
import { computeNrw, fmtPct, NRW_WINDOWS } from './nrwModel';

describe('computeNrw', () => {
  it('applies the approved formulas', () => {
    const r = computeNrw({ bulk: 1000, household: 700 });
    expect(r.nrw).toBe(300);
    expect(r.nrwPct).toBeCloseTo(30);
    expect(r.recoveryPct).toBeCloseTo(70);
    expect(r.nrwPct + r.recoveryPct).toBeCloseTo(100);
  });
  it('bulk of zero or missing gives nulls for the percentages, never NaN/Infinity', () => {
    for (const bulk of [0, null, undefined, '', 'x', -5]) {
      const r = computeNrw({ bulk, household: 10 });
      expect(r.nrwPct).toBeNull();
      expect(r.recoveryPct).toBeNull();
    }
    expect(computeNrw({ bulk: 0, household: 0 }).nrw).toBe(0);
  });
  it('missing household leaves NRW unknown, not bulk', () => {
    const r = computeNrw({ bulk: 500, household: null });
    expect(r.nrw).toBeNull();
    expect(r.nrwPct).toBeNull();
  });
  it('household above bulk yields a negative NRW (shown as is)', () => {
    const r = computeNrw({ bulk: 100, household: 120 });
    expect(r.nrw).toBe(-20);
    expect(r.nrwPct).toBeCloseTo(-20);
  });
  it('nothing supplied -> all null', () => {
    expect(computeNrw()).toEqual({ bulk: null, household: null, nrw: null, nrwPct: null, recoveryPct: null });
  });
  it('formats percentages and exposes the three windows', () => {
    expect(fmtPct(null)).toBe('—');
    expect(fmtPct(Number.NaN)).toBe('—');
    expect(fmtPct(12.345)).toBe('12.3 %');
    expect(NRW_WINDOWS.map((w) => w.label)).toEqual(['Current Day', 'Last 7 Days', 'Last 30 Days']);
  });
});
