/**
 * chartTheme
 * Single source of truth for the sky-blue chart treatment used by
 * OverviewDashboard. Exposes:
 *   - LINE_CHART_OPTIONS  → Chart.js options (moved verbatim from OverviewDashboard)
 *   - recharts tokens     → grid / axis / tooltip props matching the same look
 *   - SERIES              → named accent colours shared across pages
 */

/* ── Named series accents (matches design theme) ─────────────── */
export const SERIES = {
  blue: '#6C9BFF',
  green: '#34D399',
  amber: '#F59E0B',
  rose: '#FF6B6B',
  slate: '#94A3B8',
  indigo: '#6366F1',
  teal: '#0D9488',
  purple: '#7C3AED',
};

export const CHART_COLORS = [
  SERIES.blue, SERIES.green, SERIES.amber, SERIES.rose,
  SERIES.purple, SERIES.teal, SERIES.indigo, SERIES.slate,
];

/* ── Chart.js (reference line chart) ─────────────────────────── */
export const LINE_CHART_OPTIONS = {
  responsive: true,
  maintainAspectRatio: false,
  animation: false,
  plugins: {
    legend: { display: false },
    tooltip: {
      backgroundColor: '#0f1d30',
      borderColor: '#2a4569',
      borderWidth: 1,
      titleColor: '#9fb3cc',
      bodyColor: '#eaf2fb',
      padding: 8,
      cornerRadius: 10,
      callbacks: { label: item => `${Number(item.raw).toFixed(2)} KL` },
    },
  },
  scales: {
    x: {
      ticks: {
        color: '#8fa4bf',
        font: { size: 9, family: 'Plus Jakarta Sans' },
        maxRotation: 0,
        autoSkip: true,
        maxTicksLimit: 10,
      },
      grid: { color: 'rgba(42,69,105,0.45)' },
      border: { display: false },
    },
    y: {
      min: 0,
      ticks: {
        color: '#8fa4bf',
        font: { size: 9, family: 'Plus Jakarta Sans' },
        callback: v => Number(v).toLocaleString('en-IN', { maximumFractionDigits: 0 }),
      },
      grid: { color: 'rgba(42,69,105,0.45)' },
      border: { display: false },
    },
  },
};

/* ── Recharts equivalents of the reference tokens ────────────── */
export const RC_GRID_COLOR = 'rgba(42,69,105,0.45)';

export function rcAxisTick(size = 10) {
  return { fontSize: size, fill: '#8fa4bf', fontFamily: 'Plus Jakarta Sans' };
}

/**
 * Spreadable props for recharts <Tooltip /> matching the DESIGN.md
 * light tooltip (white body, soft hairline + soft shadow).
 * Usage: <Tooltip {...rcTooltipProps(SERIES.blue)} />
 */
export function rcTooltipProps(accent = SERIES.blue) {
  return {
    contentStyle: {
      backgroundColor: '#0f1d30',
      border: '1px solid #2a4569',
      borderRadius: 10,
      boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
      padding: 8,
    },
    labelStyle: { color: '#9fb3cc', fontSize: 11 },
    itemStyle: { color: accent, fontSize: 12, fontFamily: 'Plus Jakarta Sans' },
  };
}
