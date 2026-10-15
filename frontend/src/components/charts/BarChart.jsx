/**
 * BarChart - Chart.js bar in the navy theme.
 * items: [{ label, value, color? }] (null values are skipped by Chart.js, never drawn as 0).
 */
import { Bar } from 'react-chartjs-2';
import './chartSetup';
import { LINE_CHART_OPTIONS, SERIES } from '../ui/chartTheme';

export default function BarChart({ items, unit, color = SERIES.blue, ariaLabel = 'Bar chart', decimals = 2, horizontal = false }) {
  const data = {
    labels: items.map((i) => i.label),
    datasets: [{
      data: items.map((i) => i.value),
      backgroundColor: items.map((i) => i.color || color),
      borderRadius: 6,
      maxBarThickness: 46,
    }],
  };
  const fmt = (v) => Number(v).toLocaleString('en-IN', { maximumFractionDigits: decimals });
  const options = {
    ...LINE_CHART_OPTIONS,
    indexAxis: horizontal ? 'y' : 'x',
    plugins: {
      ...LINE_CHART_OPTIONS.plugins,
      tooltip: { ...LINE_CHART_OPTIONS.plugins.tooltip, callbacks: { label: (it) => `${fmt(it.raw)}${unit ? ` ${unit}` : ''}` } },
    },
    scales: {
      x: { ...LINE_CHART_OPTIONS.scales.x },
      y: { ...LINE_CHART_OPTIONS.scales.y, min: 0, ticks: { ...LINE_CHART_OPTIONS.scales.y.ticks, callback: (v) => fmt(v) } },
    },
  };
  return <Bar data={data} options={options} aria-label={ariaLabel} role="img" />;
}
