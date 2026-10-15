/**
 * DMA Analytics - consumption and meter status per District Metered Area.
 *
 * DATA SOURCE: the registry (dbo.Devices) has no DMA / zone assignment yet (only SiteId), and
 * there is no DMA analytics endpoint, so useDmaData() returns `null` and nothing is invented.
 * The page renders compact: selector (disabled), summary cards ("-"), and one explanatory note.
 * When the backend provides DMAs, return them from useDmaData() as
 *   { dmas: [{ id, name, meters, online, delayed, stale, consumption_kl, trend: [{ label, kl }] }] }
 * and the selector, comparison chart, trend and table below light up from that data.
 */
import { useMemo, useState } from 'react';
import { Card } from '../components/ui/Card';
import { DataPanel } from '../components/ui/DataPanel';
import BarChart from '../components/charts/BarChart';
import FlowLineChart from '../components/charts/FlowLineChart';
import { fmtInt, fmtNum } from '../utils/meterStatus';
import './Pages.css';

// eslint-disable-next-line react-refresh/only-export-components
export function useDmaData() {
  return { data: null, reason: 'Meters are not assigned to DMAs in the registry yet.' };
}

export function DmaView({ data, reason }) {
  const dmas = useMemo(() => data?.dmas ?? [], [data]);
  const [sel, setSel] = useState('');
  const shown = useMemo(() => (sel ? dmas.filter((d) => d.id === sel) : dmas), [dmas, sel]);
  const one = sel ? dmas.find((d) => d.id === sel) : null;
  const totals = useMemo(() => shown.reduce((a, d) => ({
    meters: a.meters + d.meters, online: a.online + d.online, delayed: a.delayed + d.delayed, stale: a.stale + d.stale,
    kl: d.consumption_kl != null ? a.kl + d.consumption_kl : a.kl,
  }), { meters: 0, online: 0, delayed: 0, stale: 0, kl: 0 }), [shown]);
  const has = dmas.length > 0;

  return (
    <div className="content" data-testid="page-dma">
      <Card className="auto">
        <div className="ca-search">
          <div className="ca-search-label">DMA</div>
          <select className="meter-control meter-select" aria-label="Select DMA" value={sel} disabled={!has} onChange={(e) => setSel(e.target.value)}>
            <option value="">{has ? 'All DMAs' : 'No DMAs configured'}</option>
            {dmas.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
          </select>
        </div>
      </Card>

      <section className="ov-kpis" data-testid="dma-kpis">
        <div className="ov-kpi"><div className="ov-kpi-label">DMAs</div><div className="ov-kpi-value">{has ? fmtInt(shown.length) : '—'}</div></div>
        <div className="ov-kpi"><div className="ov-kpi-label">Meters</div><div className="ov-kpi-value">{has ? fmtInt(totals.meters) : '—'}</div></div>
        <div className="ov-kpi success"><div className="ov-kpi-label">Online (≤ 24 h)</div><div className="ov-kpi-value">{has ? fmtInt(totals.online) : '—'}</div></div>
        <div className="ov-kpi warning"><div className="ov-kpi-label">Delayed (&gt; 24 h)</div><div className="ov-kpi-value">{has ? fmtInt(totals.delayed) : '—'}</div></div>
        <div className="ov-kpi danger"><div className="ov-kpi-label">Stale (&gt;48 hr)</div><div className="ov-kpi-value">{has ? fmtInt(totals.stale) : '—'}</div></div>
        <div className="ov-kpi"><div className="ov-kpi-label">Consumption (KL)</div><div className="ov-kpi-value">{has ? fmtNum(totals.kl, 2) : '—'}</div></div>
      </section>

      {!has && (
        <div className="panel-note" data-testid="dma-not-configured"><i className="fa-solid fa-circle-info" /> {reason} DMA analytics appear once meters are assigned to DMAs.</div>
      )}

      {has && (
        <div className="ov-panels">
          <DataPanel title="DMA comparison (KL)" icon="fa-chart-column" hasData={shown.some((d) => d.consumption_kl != null)} height={230} testId="dma-compare">
            <BarChart items={shown.map((d) => ({ label: d.name, value: d.consumption_kl }))} unit="KL" ariaLabel="Consumption per DMA" />
          </DataPanel>
          {one && (
            <DataPanel title={`${one.name} - consumption trend (KL)`} icon="fa-chart-line" hasData={(one.trend ?? []).length > 0} height={230} testId="dma-trend">
              <FlowLineChart points={(one.trend ?? []).map((t) => ({ label: t.label, value: t.kl }))} unit="KL" ariaLabel="DMA consumption trend" />
            </DataPanel>
          )}
        </div>
      )}
      {has && (
        <Card icon="fa-table-list" title="DMAs" className="auto">
          <div className="table-scroll" style={{ maxHeight: 320 }}>
            <table className="meter-data-table" data-testid="dma-table">
              <thead><tr><th>DMA</th><th className="align-right">Meters</th><th className="align-right">Online</th><th className="align-right">Delayed</th><th className="align-right">Stale</th><th className="align-right">Consumption (KL)</th></tr></thead>
              <tbody>
                {shown.map((d) => (
                  <tr key={d.id}><td>{d.name}</td><td className="align-right">{fmtInt(d.meters)}</td><td className="align-right">{fmtInt(d.online)}</td>
                    <td className="align-right">{fmtInt(d.delayed)}</td><td className="align-right">{fmtInt(d.stale)}</td><td className="align-right">{fmtNum(d.consumption_kl, 2)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

export default function DmaAnalyticsPage() {
  const { data, reason } = useDmaData();
  return <DmaView data={data} reason={reason} />;
}
