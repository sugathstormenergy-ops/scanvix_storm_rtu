/**
 * StatusPill + SortIndicator
 * Storm meter statuses (see utils/meterStatus.js):
 *   online -> green, delayed -> amber, offline -> red, inactive -> grey
 */
import { STATUS_LABEL } from '../../utils/meterStatus';

function statusVariant(status) {
  const s = String(status || '').toLowerCase();
  if (s === 'online' || s === 'ok') return 'active';
  if (s === 'delayed' || s === 'degraded') return 'stale';
  if (s === 'offline' || s === 'down') return 'offline';
  return 'neutral';
}

function statusLabel(status) {
  const s = String(status || '').toLowerCase();
  return STATUS_LABEL[s] || status || '—';
}

export function StatusPill({ status, label }) {
  return (
    <span className={`status-pill ${statusVariant(status)}`} data-status={status}>
      {label ?? statusLabel(status)}
    </span>
  );
}

/** Table-header sort arrow. */
export function SortIndicator({ col, sortKey, sortDir }) {
  if (sortKey !== col) return <span className="sort-indicator">↕</span>;
  return <span className="sort-indicator">{sortDir === 'asc' ? '↑' : '↓'}</span>;
}
