/**
 * PageState
 * Shared light-theme loading / error states matching the reference
 * skeleton + backend-fault-banner treatment. Replaces the per-page
 * dark-theme loading and "Backend Connection Fault" blocks.
 */

export function PageLoading({ label = 'Loading…' }) {
  return (
    <div className="page-loading">
      <span className="page-spinner" aria-hidden="true" />
      <p className="page-loading-label">{label}</p>
    </div>
  );
}

export function ErrorBanner({ message, onRetry, retryLabel = 'Retry' }) {
  return (
    <div className="backend-fault-banner">
      <i className="fa-solid fa-triangle-exclamation" />
      <span style={{ flex: 1 }}>{message}</span>
      {onRetry && (
        <button className="meter-btn" onClick={onRetry}>
          <i className="fa-solid fa-rotate-right" style={{ marginRight: 4 }} />{retryLabel}
        </button>
      )}
    </div>
  );
}

export function PageError({ title = 'Backend Connection Fault', message, onRetry, retryLabel = 'Retry' }) {
  return (
    <div className="page-error">
      <div className="page-error-box">
        <i className="fa-solid fa-triangle-exclamation page-error-icon" />
        <div className="page-error-title">{title}</div>
        <div className="page-error-message">{message}</div>
        {onRetry && (
          <button className="meter-btn primary" onClick={onRetry} style={{ marginTop: 10 }}>
            {retryLabel}
          </button>
        )}
      </div>
    </div>
  );
}
