/**
 * Schematic - the network as the registry actually models it: Site -> Meters (Devices.SiteId).
 * Nothing else is drawn: bulk sources, DMAs and consumers are not in the data model, so no such
 * nodes or connections are invented. Meter nodes are coloured by status (server time).
 * With no site-assigned meters the page is a compact "not configured" note, not an empty canvas.
 */
import { useMemo } from 'react';
import ReactFlow, { Background, Controls, MiniMap } from 'reactflow';
import 'reactflow/dist/style.css';
import { useStormData } from '../store/StormDataContext';
import { Card } from '../components/ui/Card';
import { ErrorBanner, PageError, PageLoading } from '../components/ui/PageState';
import { STATUS_LABEL, displayName, meterStatus, parseApiTimestamp } from '../utils/meterStatus';
import './Pages.css';

const STATUS_COLOR = { online: '#34D399', delayed: '#F59E0B', stale: '#FF6B6B', offline: '#94A3B8', inactive: '#475b78' };
const MAX_METERS = 400;
const COL_W = 210;
const ROW_H = 52;
const PER_COL = 12;

/** Pure layout: sites left-to-right, their meters stacked below in columns of PER_COL. */
// eslint-disable-next-line react-refresh/only-export-components
export function buildSchematic(devices, nowMs) {
  const bySite = new Map();
  for (const d of devices) {
    if (!d.site_id) continue;
    if (!bySite.has(d.site_id)) bySite.set(d.site_id, []);
    bySite.get(d.site_id).push(d);
  }
  const nodes = [];
  const edges = [];
  let x = 0;
  let shown = 0;
  let hidden = 0;
  for (const [site, list] of [...bySite.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
    const cols = Math.max(1, Math.ceil(list.length / PER_COL));
    const width = cols * COL_W;
    nodes.push({
      id: `site:${site}`, position: { x: x + (width - COL_W) / 2 + 10, y: 0 }, data: { label: `Site ${site} (${list.length})` },
      style: { width: COL_W - 20, background: '#183256', color: '#eaf2fb', border: '1.5px solid #6C9BFF', borderRadius: 12, fontWeight: 700, fontSize: 12 },
      draggable: false,
    });
    list.sort((a, b) => displayName(a).localeCompare(displayName(b))).forEach((d, i) => {
      if (shown >= MAX_METERS) { hidden += 1; return; }
      shown += 1;
      const st = meterStatus(d, nowMs);
      nodes.push({
        id: `meter:${d.device_id}`,
        position: { x: x + Math.floor(i / PER_COL) * COL_W + 10, y: 110 + (i % PER_COL) * ROW_H },
        data: { label: `${displayName(d)} · ${STATUS_LABEL[st]}` },
        style: { width: COL_W - 20, background: '#0f1d30', color: '#eaf2fb', border: `1.5px solid ${STATUS_COLOR[st]}`, borderRadius: 10, fontSize: 11 },
        draggable: false,
      });
      edges.push({ id: `e:${site}:${d.device_id}`, source: `site:${site}`, target: `meter:${d.device_id}`, style: { stroke: '#2a4569' } });
    });
    x += width + 40;
  }
  return { nodes, edges, sites: bySite.size, shown, hidden, unassigned: devices.filter((d) => !d.site_id).length };
}

export default function SchematicPage() {
  const { devices, serverTime, loading, error, hasData, refresh } = useStormData();
  const nowMs = parseApiTimestamp(serverTime);
  const model = useMemo(() => buildSchematic(devices, nowMs), [devices, nowMs]);

  if (loading && !hasData) return <PageLoading label="Loading network…" />;
  if (!hasData && error) return <div className="content"><PageError title="Cannot load network" message={error.message} onRetry={refresh} /></div>;

  return (
    <div className="content" data-testid="page-schematic">
      {error && <ErrorBanner message={`Refresh failed: ${error.message}. Showing the last successful data.`} onRetry={refresh} />}
      {model.sites === 0 ? (
        <Card icon="fa-sitemap" title="Schematic" className="auto panel-compact">
          <div className="panel-note" data-testid="schematic-empty">
            Schematic data not configured. {devices.length ? 'No meter has a site assigned yet.' : 'No meters are registered yet.'}
          </div>
        </Card>
      ) : (
        <Card icon="fa-sitemap" title={`Network: ${model.sites} site(s), ${model.shown} meter(s)`} className="auto schematic-card">
          <div className="schematic-canvas" data-testid="schematic-canvas">
            <ReactFlow nodes={model.nodes} edges={model.edges} nodesDraggable={false} nodesConnectable={false} elementsSelectable={false}
              fitView minZoom={0.1} proOptions={{ hideAttribution: true }}>
              <Background gap={18} size={1} color="#1e3350" />
              <Controls showInteractive={false} />
              {model.nodes.length > 40 && <MiniMap pannable zoomable nodeColor="#2a4569" maskColor="rgba(11,22,34,0.7)" />}
            </ReactFlow>
          </div>
          <div className="page-note" style={{ marginTop: 8 }}>
            Sites and meters come from the meter registry. Bulk sources, DMAs and consumers are not modelled yet, so none are drawn.
            {model.hidden > 0 && ` ${model.hidden} more meter(s) are not drawn (limit ${MAX_METERS}).`}
            {model.unassigned > 0 && ` ${model.unassigned} meter(s) have no site.`}
          </div>
        </Card>
      )}
    </div>
  );
}
