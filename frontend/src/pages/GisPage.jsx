/**
 * GIS - Leaflet map of registered meters. Only meters with REAL coordinates are drawn.
 *  - Filters are staged locally and committed with Apply (no SPA reload): status and view mode
 *    (Markers | Heatmap). Zone / DMA filters and DMA polygons are not offered because the registry
 *    has no zone/DMA data; they are added when the backend provides them.
 *  - Heatmap: GET /api/analytics/heatmap - KL summed over the chosen period, located meters only.
 *  - Markers are drawn on Leaflet's canvas renderer (efficient with thousands of meters).
 *  - Latitude/Longitude NULL (or invalid / 0,0) -> listed under "No location assigned".
 *  - The map view is fitted to the actual markers; there is NO default centre or
 *    placeholder coordinate. With no located meters the map is not rendered at all.
 *  - Basemap tiles are loaded by the browser from OpenStreetMap / Esri; the markers do not
 *    depend on them.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { useStormData } from '../store/StormDataContext';
import { ErrorBanner, PageError, PageLoading } from '../components/ui/PageState';
import { EmptyState } from '../components/ui/EmptyState';
import { StatusPill } from '../components/ui/StatusPill';
import MeterDetailPanel from '../components/MeterDetailPanel';
import { getPref } from '../utils/prefs';
import { useAsyncData } from '../hooks/useAsyncData';
import { fetchHeatmap } from '../services/stormApi';
import './Pages.css';
import {
  STATUS, STATUS_LABEL, displayName, fmtNum, formatAge, hasValidLocation, meterStatus, parseApiTimestamp,
} from '../utils/meterStatus';

const STATUS_COLOR = { online: '#22c55e', delayed: '#f59e0b', stale: '#ef4444', offline: '#94a3b8', inactive: '#475b78' };
const HEAT_PERIODS = [['yesterday', 'Yesterday'], ['7d', 'Last 7 Days'], ['30d', 'Last 30 Days']];

const TILES = {
  street: {
    url: 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  },
  satellite: {
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    attribution: 'Tiles &copy; Esri — Source: Esri, Maxar, Earthstar Geographics',
  },
};

/** Re-fit when the set of visible markers changes (not on every poll). */
function FitToMarkers({ points }) {
  const map = useMap();
  const key = points.map((p) => p.join(',')).join('|');
  useEffect(() => {
    if (!points.length) return;
    map.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 16 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [map, key]);
  return null;
}

/** Heat layer from backend points [{ latitude, longitude, consumption_kl }]; intensity is relative to the max. */
function HeatLayer({ points }) {
  const map = useMap();
  const layerRef = useRef(null);
  useEffect(() => {
    let cancelled = false;
    async function sync() {
      if (layerRef.current) { map.removeLayer(layerRef.current); layerRef.current = null; }
      if (!points.length) return;
      try {
        if (!L.heatLayer) {
          window.L = L;                 // leaflet.heat attaches itself to the global L
          await import('leaflet.heat');
        }
      } catch {
        return;                         // heat layer unavailable: markers keep working
      }
      if (cancelled || !L.heatLayer) return;
      const max = Math.max(...points.map((p) => p.consumption_kl));
      layerRef.current = L.heatLayer(points.map((p) => [p.latitude, p.longitude, Math.max(0.1, p.consumption_kl / max)]),
        { radius: 26, blur: 20, maxZoom: 17 }).addTo(map);
    }
    sync();
    return () => {
      cancelled = true;
      if (layerRef.current) { map.removeLayer(layerRef.current); layerRef.current = null; }
    };
  }, [map, points]);
  return null;
}

export default function GisPage() {
  const { devices, serverTime, loading, error, hasData, refresh } = useStormData();
  const nowMs = parseApiTimestamp(serverTime);
  const [draft, setDraft] = useState({ status: '', mode: 'markers', period: 'yesterday' });
  const [applied, setApplied] = useState(draft);
  const [basemap, setBasemap] = useState(() => getPref('basemap'));
  const [selectedId, setSelectedId] = useState(null);
  const closeDrawer = useCallback(() => setSelectedId(null), []);

  const heat = useAsyncData((signal) => fetchHeatmap(applied.period, signal), [applied.period],
    { enabled: applied.mode === 'heatmap', keepPrevious: false });

  const { located, unlocated } = useMemo(() => {
    const loc = [];
    const unloc = [];
    for (const d of devices) {
      const st = meterStatus(d, nowMs);
      if (applied.status && st !== applied.status) continue;
      if (hasValidLocation(d)) loc.push({ d, st, lat: Number(d.latitude), lng: Number(d.longitude) });
      else unloc.push(d);
    }
    return { located: loc, unlocated: unloc };
  }, [devices, nowMs, applied.status]);
  const points = useMemo(() => located.map((m) => [m.lat, m.lng]), [located]);
  const heatPoints = useMemo(() => {
    if (applied.mode !== 'heatmap' || !heat.data) return [];
    const ids = new Set(located.map((m) => m.d.device_id));
    return heat.data.points.filter((p) => ids.has(p.device_id));
  }, [applied.mode, heat.data, located]);
  const heatMax = heatPoints.length ? Math.max(...heatPoints.map((p) => p.consumption_kl)) : null;
  const selected = selectedId ? devices.find((d) => d.device_id === selectedId) : null;
  const dirty = draft.status !== applied.status || draft.mode !== applied.mode || draft.period !== applied.period;

  if (loading && !hasData) return <PageLoading label="Loading meters…" />;
  if (!hasData && error) return <div className="content"><PageError title="Cannot load meters" message={error.message} onRetry={refresh} /></div>;

  const tile = TILES[basemap] || TILES.street;
  const heatMode = applied.mode === 'heatmap';

  return (
    <div className="gis-page" data-testid="page-gis">
      <div className="gis-bar">
        {error && <ErrorBanner message={`Refresh failed: ${error.message}. Showing the last successful data.`} onRetry={refresh} />}
        <div className="gis-filters">
          <div className="gis-title">
            <div className="map-eyebrow">GIS</div>
            <div className="map-subtitle" data-testid="gis-counts">{located.length} located · {unlocated.length} without location</div>
          </div>
          <label className="map-filter">
            <span>Status</span>
            <select value={draft.status} onChange={(e) => setDraft({ ...draft, status: e.target.value })} aria-label="Filter by status">
              <option value="">All</option>
              {Object.values(STATUS).map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
            </select>
          </label>
          <label className="map-filter">
            <span>View</span>
            <select value={draft.mode} onChange={(e) => setDraft({ ...draft, mode: e.target.value })} aria-label="View mode">
              <option value="markers">Meters</option>
              <option value="heatmap">Heatmap</option>
            </select>
          </label>
          {draft.mode === 'heatmap' && (
            <label className="map-filter">
              <span>Period</span>
              <select value={draft.period} onChange={(e) => setDraft({ ...draft, period: e.target.value })} aria-label="Heatmap period">
                {HEAT_PERIODS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </label>
          )}
          <button type="button" className={`meter-btn primary gis-apply${dirty ? ' dirty' : ''}`} onClick={() => setApplied(draft)}>Apply</button>
          <div className="gis-basemap">
            <button type="button" className={`map-toggle-btn${basemap === 'street' ? ' active' : ''}`} onClick={() => setBasemap('street')}>Street</button>
            <button type="button" className={`map-toggle-btn${basemap === 'satellite' ? ' active' : ''}`} onClick={() => setBasemap('satellite')}>Satellite</button>
          </div>
        </div>
      </div>

      <div className="gis-map">
        {located.length === 0 ? (
          <div className="gis-empty" data-testid="gis-empty">
            <EmptyState icon="fa-map-location-dot" title="No meters with a location">
              {devices.length === 0
                ? 'No meters are registered yet.'
                : 'None of the meters has latitude/longitude assigned. Locations will appear once coordinates are added to the meter register.'}
            </EmptyState>
          </div>
        ) : (
          <MapContainer className="map-leaflet" preferCanvas bounds={L.latLngBounds(points)} boundsOptions={{ padding: [40, 40], maxZoom: 16 }} scrollWheelZoom>
            <TileLayer key={basemap} url={tile.url} attribution={tile.attribution} />
            <FitToMarkers points={points} />
            {heatMode && <HeatLayer points={heatPoints} />}
            {located.map(({ d, st, lat, lng }) => (
              <CircleMarker key={d.device_id} center={[lat, lng]} radius={heatMode ? 5 : 8}
                pathOptions={{ color: '#f0f8ff', weight: heatMode ? 1 : 2, fillColor: STATUS_COLOR[st], fillOpacity: 0.95 }}>
                <Popup>
                  <div className="map-popup">
                    <strong>{displayName(d)}</strong>
                    <div>Meter ID: {d.device_id}{d.site_id ? ` · ${d.site_id}` : ''}</div>
                    <div style={{ margin: '4px 0' }}><StatusPill status={st} /> Last seen {d.last_seen_at ? formatAge(d.last_seen_at, nowMs) : 'never'}</div>
                    {d.latest_telemetry ? (
                      <div>
                        Flow: {d.latest_telemetry.flow != null ? `${fmtNum(d.latest_telemetry.flow, 3)} ${d.latest_telemetry.flow_unit || ''}` : '—'}<br />
                        Total today: {fmtNum(d.latest_telemetry.total_today, 2)}<br />
                        Signal: {d.latest_telemetry.signal_dbm ?? '—'} dBm · Battery: {fmtNum(d.latest_telemetry.battery, 2)}
                      </div>
                    ) : <div>No telemetry yet</div>}
                    <button type="button" className="meter-btn" style={{ marginTop: 6 }} onClick={() => setSelectedId(d.device_id)}>Details</button>
                  </div>
                </Popup>
              </CircleMarker>
            ))}
          </MapContainer>
        )}
        {located.length > 0 && (
          <div id="mapLegend">
            <div className="legend-title">Status</div>
            {Object.values(STATUS).map((s) => (
              <div className="legend-row" key={s}><span className="legend-dot" style={{ background: STATUS_COLOR[s] }} />{STATUS_LABEL[s]}</div>
            ))}
            {heatMode && (
              <>
                <div className="legend-sep" />
                <div className="legend-title">Consumption ({HEAT_PERIODS.find(([k]) => k === applied.period)[1]})</div>
                {heat.loading && <div className="legend-unit">Loading…</div>}
                {heat.error && <div className="legend-unit" role="alert">Heatmap unavailable: {heat.error.message}</div>}
                {!heat.loading && !heat.error && heatMax != null && (<><div className="legend-heat" /><div className="legend-unit" data-testid="heat-legend">Highest: {fmtNum(heatMax, 2)} KL</div></>)}
                {!heat.loading && !heat.error && heatMax == null && <div className="legend-unit" data-testid="heat-empty">No consumption to show for these meters</div>}
              </>
            )}
          </div>
        )}
      </div>

      {unlocated.length > 0 && (
        <details className="gis-unlocated">
          <summary>No location assigned ({unlocated.length})</summary>
          <div className="no-location-list" data-testid="no-location-list">
            {unlocated.map((d) => <span key={d.device_id} className="no-location-chip">{displayName(d)}</span>)}
          </div>
        </details>
      )}

      {selected && <MeterDetailPanel device={selected} serverTime={serverTime} onClose={closeDrawer} />}
    </div>
  );
}
