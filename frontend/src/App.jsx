/**
 * Storm Energy RTU - application shell: topbar + page nav + routed page.
 * Primary navigation: Overview, DMA Analytics, NRW Analytics, GIS, Schematic, Consumer Analytics.
 * Retired pages (/maintenance, /settings, /gis-map) redirect; /testing, /production and
 * /analytics stay reachable by URL but are not in the primary navigation.
 */
import { lazy, Suspense, useEffect, useState } from 'react';
import { BrowserRouter, Navigate, NavLink, Outlet, Route, Routes, useSearchParams } from 'react-router-dom';
import ErrorBoundary from './components/ErrorBoundary';
import { PageLoading } from './components/ui/PageState';
import { StormDataProvider, useStormData } from './store/StormDataContext';
import { formatApiDateTime } from './utils/meterStatus';
import OverviewPage from './pages/OverviewPage';

// Heavier pages (charts, Leaflet, React Flow) are split into their own chunks.
const DmaAnalyticsPage = lazy(() => import('./pages/DmaAnalyticsPage'));
const NrwAnalyticsPage = lazy(() => import('./pages/NrwAnalyticsPage'));
const GisPage = lazy(() => import('./pages/GisPage'));
const SchematicPage = lazy(() => import('./pages/SchematicPage'));
const ConsumerAnalyticsPage = lazy(() => import('./pages/ConsumerAnalyticsPage'));
const AnalyticsPage = lazy(() => import('./pages/AnalyticsPage'));
const NotFoundPage = lazy(() => import('./pages/NotFoundPage'));
const TestingPage = lazy(() => import('./pages/TestingPage'));
const ProductionPage = lazy(() => import('./pages/ProductionPage'));

const PAGE_NAV = [
  { to: '/', end: true, icon: 'fa-solid fa-gauge-high', label: 'Overview' },
  { to: '/dma-analytics', icon: 'fa-solid fa-diagram-project', label: 'DMA Analytics' },
  { to: '/nrw-analytics', icon: 'fa-solid fa-scale-balanced', label: 'NRW Analytics' },
  { to: '/gis', icon: 'fa-solid fa-map-location-dot', label: 'GIS' },
  { to: '/schematic', icon: 'fa-solid fa-sitemap', label: 'Schematic' },
  { to: '/consumer-analytics', icon: 'fa-solid fa-user-clock', label: 'Consumer Analytics' },
];

function LiveClock() {
  const [time, setTime] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  const formatted = time.toLocaleString('en-IN', {
    timeZone: 'Asia/Kolkata',
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
  return <span className="topbar-clock" title="Browser clock (IST)"><span>{formatted}</span></span>;
}

function Shell() {
  const { refreshing, refresh, error, hasData, serverTime } = useStormData();

  return (
    <div className="storm-shell">
      <div className="storm-topbar">
        <div className="topbar-left">
          <div className="logo-badge"><i className="fa-solid fa-bolt" /></div>
          <div className="logo-info">
            <div className="logo-name">Storm Energy RTU</div>
            <div className="logo-sub">Remote Telemetry Monitoring</div>
          </div>
          {hasData && !error
            ? <div className="badge-live"><span className="dot-live" />Live</div>
            : error
              ? <div className="badge-live badge-fault" title={error.message}><span className="dot-live" />API unreachable</div>
              : null}
        </div>

        <div className="topbar-right">
          {serverTime && <span className="topbar-server-time" title="Server time of the last update">Data as of {formatApiDateTime(serverTime)}</span>}
          <LiveClock />
          <div className="topbar-divider" />
          <button
            type="button"
            className={`refresh-btn${refreshing ? ' spinning' : ''}`}
            onClick={refresh}
            disabled={refreshing}
            title="Refresh data now"
          >
            <i className="fa-solid fa-rotate" />
            {refreshing ? 'Syncing…' : 'Refresh'}
          </button>
        </div>
      </div>

      <div className="storm-hero">
        <nav className="hero-page-nav" aria-label="Pages">
          {PAGE_NAV.map(({ to, end, icon, label }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => `hero-page-btn${isActive ? ' active' : ''}`}>
              <i className={icon} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>
      </div>

      <main className="storm-main">
        <ErrorBoundary>
          <Suspense fallback={<PageLoading label="Loading page…" />}>
            <Outlet />
          </Suspense>
        </ErrorBoundary>
      </main>
    </div>
  );
}

/** Bare layout for the dev/KT Testing page: no topbar, no hero, no business navigation. */
function BareShell() {
  return (
    <main className="storm-main storm-main-bare" data-testid="bare-shell">
      <ErrorBoundary>
        <Suspense fallback={<PageLoading label="Loading page…" />}>
          <Outlet />
        </Suspense>
      </ErrorBoundary>
    </main>
  );
}

/** The former Protocol Test Log (/test-logs, ?tab=mqtt) now lives in /testing. */
function LegacyTestLogsRedirect() {
  const [params] = useSearchParams();
  return <Navigate to={params.get('tab') === 'mqtt' ? '/testing?protocol=MQTT' : '/testing'} replace />;
}

export function AppRoutes() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<OverviewPage />} />
        <Route path="production" element={<ProductionPage />} />
        <Route path="analytics" element={<AnalyticsPage />} />
        <Route path="dma-analytics" element={<DmaAnalyticsPage />} />
        <Route path="nrw-analytics" element={<NrwAnalyticsPage />} />
        <Route path="gis" element={<GisPage />} />
        <Route path="schematic" element={<SchematicPage />} />
        <Route path="consumer-analytics" element={<ConsumerAnalyticsPage />} />
        <Route path="gis-map" element={<Navigate to="/gis" replace />} />
        <Route path="maintenance/*" element={<Navigate to="/" replace />} />
        <Route path="settings" element={<Navigate to="/" replace />} />
        <Route path="test-logs" element={<LegacyTestLogsRedirect />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
      <Route element={<BareShell />}>
        <Route path="testing" element={<TestingPage />} />
      </Route>
    </Routes>
  );
}

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <StormDataProvider>
          <AppRoutes />
        </StormDataProvider>
      </BrowserRouter>
    </ErrorBoundary>
  );
}
