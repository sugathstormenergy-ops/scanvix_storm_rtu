/** DonutChart - proportions of a whole, e.g. meters per status. items: [{ label, value, color }] */
import { Doughnut } from 'react-chartjs-2';
import './chartSetup';
import { LINE_CHART_OPTIONS } from '../ui/chartTheme';

export default function DonutChart({ items, ariaLabel = 'Distribution' }) {
  const shown = items.filter((i) => i.value > 0);
  const data = {
    labels: shown.map((i) => i.label),
    datasets: [{ data: shown.map((i) => i.value), backgroundColor: shown.map((i) => i.color), borderColor: '#0f1d30', borderWidth: 2 }],
  };
  const options = {
    responsive: true, maintainAspectRatio: false, animation: false, cutout: '62%',
    plugins: {
      legend: { position: 'right', labels: { color: '#c9d8ea', boxWidth: 10, font: { size: 11, family: 'Plus Jakarta Sans' } } },
      tooltip: { ...LINE_CHART_OPTIONS.plugins.tooltip, callbacks: { label: (it) => `${it.label}: ${it.raw}` } },
    },
  };
  return <Doughnut data={data} options={options} aria-label={ariaLabel} role="img" />;
}
