/**
 * DataPanel - a card that never leaves a large blank area behind.
 *   loading  -> compact skeleton strip (fixed small height)
 *   error    -> compact error line with Retry
 *   !hasData -> title + one small "No data available" line (compact) or nothing when `hideWhenEmpty`
 *   hasData  -> the children inside a body of the requested height
 */
import { Card } from './Card';

export function DataPanel({ title, icon, action, hasData, loading = false, error = null, onRetry,
  emptyText = 'No data available', hideWhenEmpty = false, height = 240, className = '', testId, children }) {
  if (!loading && !error && !hasData && hideWhenEmpty) return null;
  let body;
  if (error) {
    body = (
      <div className="panel-note panel-note-error" role="alert">
        <i className="fa-solid fa-triangle-exclamation" /> {error.message || String(error)}
        {onRetry && <button type="button" className="meter-btn" onClick={onRetry}>Retry</button>}
      </div>
    );
  } else if (loading && !hasData) {
    body = <div className="skeleton" style={{ height: 36, borderRadius: 8 }} />;
  } else if (!hasData) {
    body = <div className="panel-note" data-testid={testId ? `${testId}-empty` : undefined}>{emptyText}</div>;
  } else {
    body = <div className="panel-body" style={{ height }} data-testid={testId}>{children}</div>;
  }
  return (
    <Card icon={icon} title={title} action={action} className={`auto panel-compact ${className}`}>
      {body}
    </Card>
  );
}
