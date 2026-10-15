export function EmptyState({ icon = 'fa-circle-info', title, children, testId }) {
  return (
    <div className="empty-state" data-testid={testId}>
      <i className={`fa-solid ${icon}`} />
      {title && <strong>{title}</strong>}
      {children && <div>{children}</div>}
    </div>
  );
}

/** Disabled write-action placeholder: the action exists in the API but is not enabled in this UI. */
export const AUTH_REQUIRED_TEXT = 'Requires authentication (not yet enabled)';

export function AuthRequiredAction({ icon = 'fa-pen', label }) {
  return (
    <span className="auth-required" data-testid="auth-required">
      <button type="button" className="meter-btn" disabled aria-disabled="true" title={AUTH_REQUIRED_TEXT}>
        <i className={`fa-solid ${icon}`} style={{ marginRight: 4 }} />{label}
      </button>
      <span className="auth-required-note"><i className="fa-solid fa-lock" />{AUTH_REQUIRED_TEXT}</span>
    </span>
  );
}
