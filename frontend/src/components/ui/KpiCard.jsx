/**
 * KpiCard
 * Shared KPI tile (.kpi-card c-{color})
 * used by the Production and Analytics pages.
 * Colors: blue | green | amber | rose | indigo | teal | purple
 */

const GRADIENTS = {
  blue: 'linear-gradient(90deg,#6C9BFF,#B9A7FF)',
  green: 'linear-gradient(90deg,#34D399,#6EE7B7)',
  amber: 'linear-gradient(90deg,#F59E0B,#FCD34D)',
  rose: 'linear-gradient(90deg,#FF6B6B,#FDA4AF)',
  indigo: 'linear-gradient(90deg,#6366F1,#B9A7FF)',
  teal: 'linear-gradient(90deg,#0D9488,#34D399)',
  purple: 'linear-gradient(90deg,#7C3AED,#B9A7FF)',
};

export function KpiCard({ title, value, color = 'blue', icon = 'chart-line', loading = false, subtitle, progress = false }) {
  return (
    <div className={`kpi-card c-${color}`}>
      <div className="kpi-header">
        <div className={`kpi-icon ${color}`}><i className={`fa-solid fa-${icon}`} /></div>
      </div>
      <div className="kpi-value">
        {loading
          ? <span className="skeleton" style={{ display: 'inline-block', width: 52, height: 16, borderRadius: 4 }} />
          : (value ?? '—')}
      </div>
      <div className="kpi-label">{title}</div>
      {subtitle && <div className="kpi-sub">{subtitle}</div>}
      {progress && (
        <div className="kpi-progress">
          <div className="kpi-progress-fill" style={{ width: '100%', background: GRADIENTS[color] || GRADIENTS.blue }} />
        </div>
      )}
    </div>
  );
}
