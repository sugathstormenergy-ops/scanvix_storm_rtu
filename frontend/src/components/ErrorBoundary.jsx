/**
 * ErrorBoundary — catches rendering errors so a bug shows a message instead of a blank page.
 */
import { Component } from 'react';

export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('[ErrorBoundary] rendering error:', error, errorInfo);
  }

  render() {
    if (this.state.error) {
      return (
        <div className="page-error" style={{ minHeight: '100vh' }}>
          <div className="page-error-box">
            <i className="fa-solid fa-triangle-exclamation page-error-icon" />
            <div className="page-error-title">Application error</div>
            <div className="page-error-message">
              An unexpected error occurred while rendering this page. Details are in the browser console.
            </div>
            <button className="meter-btn primary" style={{ marginTop: 10 }} onClick={() => window.location.reload()}>
              Reload
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
