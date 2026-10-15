import { afterEach, vi } from 'vitest';
import { cleanup } from '@testing-library/react';

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  try { window.localStorage.clear(); } catch { /* ignore */ }
});

// jsdom lacks ResizeObserver / matchMedia (Recharts, React Flow).
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class { observe() {} unobserve() {} disconnect() {} };
}
if (!window.matchMedia) {
  window.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} });
}

// jsdom has no canvas 2D context, so Chart.js cannot draw (and crashes when it re-renders a
// chart whose canvas it never acquired). Unit tests render a placeholder canvas instead;
// real chart rendering is covered by the Chromium E2E run (e2e/smoke.mjs).
vi.mock('react-chartjs-2', async () => {
  const React = await import('react');
  const Stub = (props) => React.createElement('canvas', { 'data-testid': 'chartjs-stub', 'aria-label': props['aria-label'] });
  return { Line: Stub, Bar: Stub, Pie: Stub, Doughnut: Stub };
});
