/**
 * Card
 * Shared card shell matching the OverviewDashboard treatment:
 * .card → .card-header → .card-title (FA icon + label) + optional action slot.
 * `flush` removes body padding (maps, schematics).
 */

export function Card({ icon, title, action, flush = false, className = '', style, headerStyle, children }) {
  return (
    <div
      className={`card${className ? ` ${className}` : ''}`}
      style={flush ? { padding: 0, overflow: 'hidden', ...style } : style}
    >
      {(title || action) && (
        <div className="card-header" style={flush ? { padding: '12px 14px', marginBottom: 0, ...headerStyle } : headerStyle}>
          <div className="card-title">
            {icon && <i className={`fa-solid ${icon}`} />}
            {title}
          </div>
          {action && <div className="card-action">{action}</div>}
        </div>
      )}
      {children}
    </div>
  );
}
