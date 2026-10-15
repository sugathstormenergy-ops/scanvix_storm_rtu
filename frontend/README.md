# Storm Energy RTU — web frontend

React 19 + Vite single-page app for monitoring Storm Energy RTU meters. It is served
by the `storm-frontend` container and reached **only through the reverse proxy**
(`https://<server>/`). It has no host port of its own.

## Pages

| Route | Purpose | Data |
|---|---|---|
| `/` | **Overview**: 6 KPI cards (Total Meters, Active, Online ≤24 h, Delayed >24 h, Stale >48 h, Total Today KL), meter status donut, daily consumption (7 d), meters by site, meter table + detail drawer. Panels with no data collapse or hide. | `GET /api/devices/latest`, `GET /api/analytics/overview`, `GET /api/analytics/daily` |
| `/dma-analytics` | **DMA Analytics**: DMA selector, KPIs, comparison/trend/table. The registry has no DMA data yet, so it shows one compact "not configured" note (nothing invented). | none yet (`useDmaData()` seam) |
| `/nrw-analytics` | **NRW Analytics**: 6 KPI cards, Current Day / Last 7 Days / Last 30 Days, water-balance charts, scrollable table. Formulas in `utils/nrwModel.js`. No bulk/household classification exists yet, so values are dashes and charts are hidden. | none yet (`useNrwData()` seam) |
| `/gis` | **GIS**: Leaflet map of meters with real coordinates only; status filter, view mode Meters/Heatmap, heatmap period, **Apply**; canvas markers. Zone/DMA filters and polygons appear when the backend provides them. | `GET /api/devices/latest`, `GET /api/analytics/heatmap` |
| `/schematic` | **Schematic**: Site → Meters (from `Devices.SiteId`) with React Flow; compact "not configured" note when no meter has a site. | `GET /api/devices/latest` |
| `/consumer-analytics?device=<id>` | **Consumer Analytics**: meter search (ID, name, IMEI, site), header, Last 24 h / Yesterday / Last month cards + bar chart, flow trend (24h/7d/30d, bucketed server-side), paginated history table. | `GET /api/analytics/devices/{id}/{consumption,trend,history}` |
| `/testing` (`/test-logs` redirects) | Internal **Protocol Monitor**: everything arriving at the server (not in the primary navigation). | `GET /api/diagnostics/{summary,sources,packets,packets/{id}}` |
| `/production?device=<id>`, `/analytics?device=<id>` | Earlier per-meter pages, still reachable by URL, not in the primary navigation. | `GET /api/devices/latest`, `GET /api/telemetry/{device_id}` |
| `/gis-map`, `/maintenance/*`, `/settings` | Retired: redirect to `/gis` or `/`. | — |

Primary navigation (exactly six): Overview, DMA Analytics, NRW Analytics, GIS, Schematic, Consumer Analytics.

Consumption (KL) is always aggregated by the backend (`/api/analytics/*`): the sum, per day, of the highest
`TotalToday` reported, converted to KL only for units with a known conversion (m3, KL, L, ML). Meters with an
unknown unit are excluded and reported, never summed.

## Meter status rules (fixed)

Computed in `src/utils/meterStatus.js` from `last_seen_at` and the `server_time` returned
with the same response. The browser's clock and timezone are never used.

| Status | Rule |
|---|---|
| Online | active and last seen ≤ 24 h ago |
| Delayed | active and last seen > 24 h and ≤ 48 h ago |
| Stale | active and last seen > 48 h ago |
| Offline | active and never communicated (`last_seen_at` is null) |
| Inactive | `is_active = false`; counted only in Total Meters |

Offline = active and never communicated (never counted as online).

Total Today (KL) = sum of consumption of all active meters over the last 24 hours, computed by the backend
(`GET /api/analytics/overview`). Meters whose unit cannot be converted to KL are excluded and reported
("N meter(s) excluded"); with nothing convertible the card shows an em dash.

## Rules the code follows

- All requests are same-origin (`/api/...`, `/health`) and GET only (`src/services/apiClient.js`).
- No mock data and no fallback: a failed request shows an error state. After a failed
  refresh, the last successful data stays visible with a warning banner.
- Write actions (edit configuration, send command, edit device) are shown disabled with
  "Requires authentication (not yet enabled)".
- No service worker or PWA. `index.html` is served `no-store`; hashed `/assets/*` are immutable.
- Fonts and icons are bundled. Only the GIS basemap tiles (OpenStreetMap / Esri) come
  from the Internet, loaded by the browser. Markers work without them.

## Development

```bash
npm ci
npm run dev        # http://127.0.0.1:5173; /api and /health go to STORM_API_DEV_TARGET (default http://127.0.0.1:8000)
npm run lint
npm test           # vitest (status rules, API client, pages with a stubbed fetch)
npm run build      # -> dist/
```

End-to-end (test-only; uses the production nginx configs with a local nginx, a fixture
API on SQLite, and Chromium):

```bash
python e2e/fixture_api.py 18000 &      # needs the backend requirements
npm run build && e2e/proxy-harness.sh start
npm i --no-save playwright-core
E2E_BASE=https://127.0.0.1:19443 node e2e/smoke.mjs
e2e/proxy-harness.sh stop
```

## Container

`Dockerfile`: `node` build stage (`npm ci`, `npm run build`), then
`nginxinc/nginx-unprivileged` (non-root, port 8080) with `dist/` and `nginx.conf` only.
In `compose.yml` it runs read-only with `cap_drop: ALL` and no published port. The reverse
proxy (`docker/nginx/templates/storm.conf.template`) routes `/api/`, `/health` and the API
docs to `storm-api` and everything else to `storm-frontend`.
