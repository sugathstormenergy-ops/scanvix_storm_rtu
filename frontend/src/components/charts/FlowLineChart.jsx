/**
 * FlowLineChart — Chart.js line in the base dashboard's style.
 * points: [{ label, value }] (value may be null -> gap). unit: shown in the tooltip.
 */
import { Line } from 'react-chartjs-2';
import './chartSetup';
import { LINE_CHART_OPTIONS, SERIES } from '../ui/chartTheme';

export default function FlowLineChart({ points, unit, color = SERIES.blue, ariaLabel = 'Flow trend' }) {
  const data = {
    labels: points.map((p) => p.label),
    datasets: [{
      data: points.map((p) => p.value),
      borderColor: color,
      backgroundColor: `${color}22`,
      fill: true,
      tension: 0.3,
      pointRadius: points.length > 60 ? 0 : 2,
      borderWidth: 2,
      spanGaps: false,
    }],
  };
  const options = {
    ...LINE_CHART_OPTIONS,
    plugins: {
      ...LINE_CHART_OPTIONS.plugins,
      tooltip: {
        ...LINE_CHART_OPTIONS.plugins.tooltip,
        callbacks: { label: (item) => `${Number(item.raw).toLocaleString('en-IN', { maximumFractionDigits: 3 })}${unit ? ` ${unit}` : ''}` },
      },
    },
    scales: {
      ...LINE_CHART_OPTIONS.scales,
      y: {
        ...LINE_CHART_OPTIONS.scales.y,
        min: undefined,
        beginAtZero: true,
        ticks: { ...LINE_CHART_OPTIONS.scales.y.ticks, callback: (v) => Number(v).toLocaleString('en-IN', { maximumFractionDigits: 2 }) },
      },
    },
  };
  return <Line data={data} options={options} aria-label={ariaLabel} role="img" />;
}
