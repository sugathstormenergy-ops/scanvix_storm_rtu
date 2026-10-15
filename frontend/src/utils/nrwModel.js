/**
 * NRW (non-revenue water) model - the ONLY place the NRW formulas live.
 *
 *   NRW Volume = Bulk Input - Household Consumption
 *   NRW %      = NRW Volume / Bulk Input * 100
 *   Recovery % = Household Consumption / Bulk Input * 100
 *
 * Every value is null (rendered as an em dash) when it cannot be computed: missing inputs,
 * non-finite numbers, or Bulk Input <= 0 (no division by zero, never NaN/Infinity).
 * NRW volume may legitimately be negative (household > bulk = metering error); it is shown as is.
 */
export const NRW_WINDOWS = Object.freeze([
  { key: 'current_day', label: 'Current Day' },
  { key: 'last_7d', label: 'Last 7 Days' },
  { key: 'last_30d', label: 'Last 30 Days' },
]);

const num = (v) => (v == null || v === '' || !Number.isFinite(Number(v)) ? null : Number(v));

export function computeNrw({ bulk, household } = {}) {
  const b = num(bulk);
  const h = num(household);
  const nrw = b != null && h != null ? b - h : null;
  const ok = b != null && b > 0;
  return {
    bulk: b,
    household: h,
    nrw,
    nrwPct: ok && nrw != null ? (nrw / b) * 100 : null,
    recoveryPct: ok && h != null ? (h / b) * 100 : null,
  };
}

export function fmtPct(v) {
  return v == null || !Number.isFinite(v) ? '—' : `${v.toLocaleString('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })} %`;
}
