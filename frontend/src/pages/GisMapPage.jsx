/**
 * GIS Map — only meters with REAL coordinates are drawn.
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
import { Card } from '../components/ui/Card';
import { ErrorBanner, PageError, PageLoading } from '../components/ui/PageState';
import { EmptyState } from '../components/ui/EmptyState';
import { StatusPill } from '../components/ui/StatusPill';
import MeterDetailPanel from '../components/MeterDetailPanel';
import { getPref } from '../utils/prefs';
import {
  STATUS, STATUS_LABEL, displayName, fmtNum, formatAge, hasValidLocation, meterStatus, parseApiTimestamp,
} from '../utils/meterStatus';

const STATUS_COLOR = { online: '#22c55e', delayed: '#f59e0b', offline: '#ef4444', inactive: '#94a3b8' };

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

/** Heat layer weighted by current flow (meters without a flow value are excluded). */
function HeatLayer({ markers, visible }) {
  const map = useMap();
  const layerRef = useRef(null);
  useEffect(() => {
    let cancelled = false;
    async function sync() {
      if (layerRef.current) { map.removeLayer(layerRef.current); layerRef.current = null; }
      if (!visible) return;
      try {
        if (!L.heatLayer) {
          window.L = L;                 // leaflet.heat attaches itself to the global L
          await import('leaflet.heat');
        }
      } catch {
        return;                         // heat layer unavailable: markers keep working
      }
      if (cancelled || !L.heatLayer) return;
      const withFlow = markers.filter((m) => m.flow != null && Number.isFinite(m.flow) && m.flow > 0);
      if (!withFlow.length) return;
      const max = Math.max(...withFlow.map((m) => m.flow));
      layerRef.current = L.heatLayer(withFlow.map((m) => [m.lat, m.lng, Math.max(0.1, m.flow / max)]), { radius: 22, blur: 18, maxZoom: 17 }).addTo(map);
    }
    sync();
    return () => {
      cancelled = true;
      if (layerRef.current) { map.removeLayer(layerRef.current); layerRef.current = null; }
    };
  }, [map, markers, visible]);
  return null;
}

export default function GisMapPage() {
  const { devices, serverTime, loading, error, hasData, refresh } = useStormData();
  const nowMs = parseApiTimestamp(serverTime);
  const [statusFilter, setStatusFilter] = useState('');
  const [basemap, setBasemap] = useState(() => getPref('basemap'));
  const [heat, setHeat] = useState(false);
  const [selectedId, setSelectedId] = useState(null);
  const closeDrawer = useCallback(() => setSelectedId(null), []);

  const { located, unlocated } = useMemo(() => {
    const loc = [];
    const unloc = [];
    for (const d of devices) {
      const st = meterStatus(d, nowMs);
      if (statusFilter && st !== statusFilter) continue;
      if (hasValidLocation(d)) {
        loc.push({ d, st, lat: Number(d.latitude), lng: Number(d.longitude), flow: d.latest_telemetry?.flow ?? null });
      } else {
        unloc.push(d);
      }
    }
    return { located: loc, unlocated: unloc };
  }, [devices, nowMs, statusFilter]);
  const points = useMemo(() => located.map((m) => [m.lat, m.lng]), [located]);
  const selected = selectedId ? devices.find((d) => d.device_id === selectedId) : null;

  if (loading && !hasData) return <PageLoading label="Loading meters…" />;
  if (!hasData && error) return <div className="content"><PageError title="Cannot load meters" message={error.message} onRetry={refresh} /></div>;

  const tile = TILES[basemap] || TILES.street;

  return (
    <div className="map-layout" data-testid="page-gis">
      {error && <ErrorBanner message={`Refresh failed: ${error.message}. Showing the last successful data.`} onRetry={refresh} />}
      <div className="map-header">
        <div className="map-title-block">
          <div className="map-eyebrow">GIS</div>
          <div className="map-title">Meter locations</div>
          <div className="map-subtitle">{located.length} located · {unlocated.length} without location</div>
        </div>
        <div className="map-filters">
          <label className="map-filter">
            <span>Status</span>
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="Filter by status">
              <option value="">All</option>
              {Object.values(STATUS).map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
            </select>
          </label>
          <button type="button" className={`map-toggle-btn${basemap === 'street' ? ' active' : ''}`} onClick={() => setBasemap('street')}>Street</button>
          <button type="button" className={`map-toggle-btn${basemap === 'satellite' ? ' active' : ''}`} onClick={() => setBasemap('satellite')}>Satellite</button>
          <button type="button" className={`map-toggle-btn${heat ? ' active' : ''}`} onClick={() => setHeat((h) => !h)} aria-pressed={heat}>Flow heatmap</button>
        </div>
      </div>

      <div className="map-container">
        {located.length === 0 ? (
          <div className="map-state" data-testid="gis-empty">
            <EmptyState icon="fa-map-location-dot" title="No meters with a location">
              {devices.length === 0
                ? 'No meters are registered yet.'
                : 'None of the meters has latitude/longitude assigned. Locations will appear once coordinates are added to the meter register.'}
            </EmptyState>
          </div>
        ) : (
          <MapContainer className="map-leaflet" bounds={L.latLngBounds(points)} boundsOptions={{ padding: [40, 40], maxZoom: 16 }} scrollWheelZoom>
            <TileLayer key={basemap} url={tile.url} attribution={tile.attribution} />
            <FitToMarkers points={points} />
            <HeatLayer markers={located} visible={heat} />
            {located.map(({ d, st, lat, lng }) => (
              <CircleMarker key={d.device_id} center={[lat, lng]} radius={8}
                pathOptions={{ color: '#ffffff', weight: 2, fillColor: STATUS_COLOR[st], fillOpacity: 0.95 }}>
                <Popup>
                  <div className="map-popup">
                    <strong>{displayName(d)}</strong>
                    <div>{d.device_id}{d.site_id ? ` · ${d.site_id}` : ''}</div>
                    <div style={{ margin: '4px 0' }}><StatusPill status={st} /> {formatAge(d.last_seen_at, nowMs)}</div>
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
            {heat && (<><div className="legend-sep" /><div className="legend-title">Flow</div><div className="legend-heat" /><div className="legend-unit">Relative to highest current flow</div></>)}
          </div>
        )}
      </div>

      <Card icon="fa-location-crosshairs" title={`No location assigned (${unlocated.length})`} className="auto">
        {unlocated.length ? (
          <div className="no-location-list" data-testid="no-location-list">
            {unlocated.map((d) => <span key={d.device_id} className="no-location-chip">{displayName(d)}</span>)}
          </div>
        ) : <div className="page-note">Every meter in this view has a location.</div>}
      </Card>

      {selected && <MeterDetailPanel device={selected} serverTime={serverTime} onClose={closeDrawer} />}
    </div>
  );
}
