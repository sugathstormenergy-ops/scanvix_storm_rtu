/**
 * NRW Analytics - water balance: Bulk Input vs Household Consumption.
 *
 * DATA SOURCE: the registry (dbo.Devices) has NO bulk / household classification yet, so the
 * backend cannot aggregate NRW and useNrwData() returns `null`. The page then shows its six KPI
 * cards as "-", a compact explanation, and a compact three-row table - no charts, no invented
 * numbers. When a backend NRW summary exists, return it from useNrwData() in this shape:
 *   { windows: { current_day|last_7d|last_30d: { bulk, household, meters } },
 *     trend:   [{ label, bulk, household }] }   // KL
 * and every KPI, chart and table row below is computed from it by utils/nrwModel.js.
 *
 * Layout (spec): grid rows  auto | minmax(220px, .82fr) | minmax(0, 1fr); the table is the only
 * scrolling region and keeps its header fixed.
 */
import { useState } from 'react';
import { Card } from '../components/ui/Card';
import BarChart from '../components/charts/BarChart';
import FlowLineChart from '../components/charts/FlowLineChart';
import { fmtNum } from '../utils/meterStatus';
import { NRW_WINDOWS, computeNrw, fmtPct } from '../utils/nrwModel';
import './Pages.css';

/** Placeholder seam for a future backend endpoint. No data source exists today. */
// eslint-disable-next-line react-refresh/only-export-components
export function useNrwData() {
  return { data: null, reason: 'Bulk and household meters are not classified in the meter registry yet.' };
}

function Kpi({ label, value, unit, testId, sub }) {
  return (
    <div className="nrw-kpi" data-testid={testId}>
      <div className="nrw-kpi-label">{label}</div>
      <div className="nrw-kpi-value">{value}{unit && value !== '—' ? <span className="ov-kpi-unit">{unit}</span> : null}</div>
      {sub && <div className="ov-kpi-sub">{sub}</div>}
    </div>
  );
}

export function NrwView({ data, reason }) {
  const [win, setWin] = useState('current_day');
  const rows = NRW_WINDOWS.map((w) => ({ ...w, ...computeNrw(data?.windows?.[w.key] ?? {}), meters: data?.windows?.[w.key]?.meters ?? null }));
  const cur = rows.find((r) => r.key === win);
  const trend = data?.trend ?? [];
  const hasTrend = trend.some((t) => t.bulk != null || t.household != null);

  return (
    <div className="nrw-dashboard" data-testid="page-nrw">
      <section className="nrw-kpi-section">
        <div className="nrw-toolbar">
          <div className="nrw-title">NRW Dashboard</div>
          <div className="seg" role="tablist" aria-label="NRW period">
            {NRW_WINDOWS.map((w) => (
              <button key={w.key} type="button" role="tab" aria-selected={win === w.key} className={`seg-btn${win === w.key ? ' active' : ''}`}
                onClick={() => setWin(w.key)}>{w.label}</button>
            ))}
          </div>
        </div>
        <div className="nrw-kpis" data-testid="nrw-kpis">
          <Kpi testId="nrw-bulk" label="Bulk Input" value={cur.bulk != null ? fmtNum(cur.bulk, 2) : '—'} unit="KL" />
          <Kpi testId="nrw-household" label="Household Consumption" value={cur.household != null ? fmtNum(cur.household, 2) : '—'} unit="KL" />
          <Kpi testId="nrw-volume" label="NRW Volume" value={cur.nrw != null ? fmtNum(cur.nrw, 2) : '—'} unit="KL" />
          <Kpi testId="nrw-pct" label="NRW %" value={fmtPct(cur.nrwPct)} />
          <Kpi testId="nrw-recovery" label="Recovery %" value={fmtPct(cur.recoveryPct)} />
          <Kpi testId="nrw-meters" label="Classified Meters" value={cur.meters != null ? String(cur.meters) : '—'} />
        </div>
        {!data && <div className="panel-note" data-testid="nrw-not-configured"><i className="fa-solid fa-circle-info" /> {reason} NRW needs a bulk-input and household classification per meter.</div>}
      </section>

      {hasTrend && (
        <section className="nrw-charts" data-testid="nrw-charts">
          <Card icon="fa-scale-balanced" title="Water balance (KL)" className="auto nrw-chart-card">
            <div className="chart-wrap"><BarChart ariaLabel="Bulk input vs household consumption"
              items={[{ label: 'Bulk Input', value: cur.bulk, color: '#6C9BFF' }, { label: 'Household', value: cur.household, color: '#34D399' }, { label: 'NRW', value: cur.nrw != null && cur.nrw >= 0 ? cur.nrw : null, color: '#FF6B6B' }]} unit="KL" /></div>
          </Card>
          <Card icon="fa-chart-line" title="Bulk input trend (KL)" className="auto nrw-chart-card">
            <div className="chart-wrap"><FlowLineChart points={trend.map((t) => ({ label: t.label, value: t.bulk }))} unit="KL" ariaLabel="Bulk input trend" /></div>
          </Card>
          <Card icon="fa-chart-line" title="NRW % trend" className="auto nrw-chart-card">
            <div className="chart-wrap"><FlowLineChart color="#FF6B6B" unit="%" ariaLabel="NRW percentage trend"
              points={trend.map((t) => ({ label: t.label, value: computeNrw(t).nrwPct }))} /></div>
          </Card>
        </section>
      )}

      <section className="nrw-table-panel" data-testid="nrw-table-panel">
        <div className="nrw-table-head">Water balance by period</div>
        <div className="nrw-table-body">
          <table className="meter-data-table nrw-table" data-testid="nrw-table">
            <thead>
              <tr><th>Period</th><th className="align-right">Bulk Input (KL)</th><th className="align-right">Household Consumption (KL)</th>
                <th className="align-right">NRW (KL)</th><th className="align-right">NRW %</th><th className="align-right">Recovery %</th></tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.key} data-testid={`nrw-row-${r.key}`}>
                  <td>{r.label}</td>
                  <td className="align-right">{fmtNum(r.bulk, 2)}</td>
                  <td className="align-right">{fmtNum(r.household, 2)}</td>
                  <td className="align-right">{fmtNum(r.nrw, 2)}</td>
                  <td className="align-right">{fmtPct(r.nrwPct)}</td>
                  <td className="align-right">{fmtPct(r.recoveryPct)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

export default function NrwAnalyticsPage() {
  const { data, reason } = useNrwData();
  return <NrwView data={data} reason={reason} />;
}
