import { describe, expect, it, vi } from 'vitest';
import { render, screen, within, fireEvent } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { StormDataProvider } from './store/StormDataContext';
import { AppRoutes } from './App';
import { defaultRoutes, stubApi, DEVICES_LATEST, ANALYTICS_OVERVIEW, CONSUMPTION_RTU001, HISTORY_RTU001 } from './test/fixtures';

function renderAt(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <StormDataProvider refreshMs={0}>
        <AppRoutes />
      </StormDataProvider>
    </MemoryRouter>,
  );
}

const kpi = async (id) => (await screen.findByTestId(id)).querySelector('.ov-kpi-value').textContent;

describe('shell + Overview', () => {
  it('shows the six KPIs: registry counts by SERVER time + Total Today (KL) from the analytics API', async () => {
    stubApi(defaultRoutes());
    renderAt('/');
    await screen.findByText('Pump House 1');
    expect(await kpi('kpi-total')).toBe('5');
    expect(await kpi('kpi-active')).toBe('4');
    expect(await kpi('kpi-online')).toBe('2');     // RTU-001 (1 h), RTU-002 (exactly 24 h)
    expect(await kpi('kpi-delayed')).toBe('0');    // nobody is 24-48 h old
    expect(await kpi('kpi-stale')).toBe('1');      // RTU-003 last seen 5 days ago
    await vi.waitFor(async () => expect(await kpi('kpi-total-today')).toMatch(/^1,234\.50\s*KL$/));
    expect(screen.getByTestId('total-today-help').textContent).toBe('Sum of consumption of all meters in KL for the last 24 hours');
    expect(screen.getByText('Storm Energy RTU')).toBeTruthy();
  });

  it('Total Today is unavailable (an em dash), never 0, when the backend has nothing convertible', async () => {
    stubApi(defaultRoutes({ '/api/analytics/overview': { ...ANALYTICS_OVERVIEW, total_kl: null, meters_counted: 0, meters_excluded: 1 } }));
    renderAt('/');
    await screen.findByText('Pump House 1');
    await vi.waitFor(() => expect(screen.getByTestId('kpi-total-today').textContent).toContain('1 meter(s) excluded'));
    expect(await kpi('kpi-total-today')).toBe('—');
  });

  it('charts show real data: status split and daily consumption', async () => {
    stubApi(defaultRoutes());
    renderAt('/');
    expect(await screen.findByTestId('status-chart')).toBeTruthy();
    expect(await screen.findByTestId('daily-chart')).toBeTruthy();
    expect(screen.getByTestId('site-summary')).toBeTruthy();
  });

  it('meter table lists every device with the right status', async () => {
    stubApi(defaultRoutes());
    renderAt('/');
    const table = await screen.findByTestId('meter-table');
    await within(table).findByText('Pump House 1');
    const statusOf = (label) => within(table).getByText(label).closest('tr').querySelector('.status-pill').dataset.status;
    expect(statusOf('Pump House 1')).toBe('online');
    expect(statusOf('RTU-002')).toBe('online');
    expect(statusOf('RTU-003')).toBe('stale');
    expect(statusOf('RTU-004')).toBe('offline');
    expect(statusOf('RTU-005')).toBe('inactive');
  });

  it('status filter narrows the table', async () => {
    stubApi(defaultRoutes());
    renderAt('/');
    await screen.findByText('Pump House 1');
    fireEvent.change(screen.getByLabelText('Filter by status'), { target: { value: 'stale' } });
    const rows = within(screen.getByTestId('meter-table')).getAllByRole('row');
    expect(rows).toHaveLength(2); // header + RTU-003
    expect(within(rows[1]).getByText('RTU-003')).toBeTruthy();
  });

  it('API failure shows an error state and NO data (no mock fallback)', async () => {
    stubApi(defaultRoutes({ '/api/devices/latest': { httpStatus: 500, body: { detail: 'Internal Server Error' } } }));
    renderAt('/');
    expect(await screen.findByText('Cannot load meters')).toBeTruthy();
    expect(screen.getByText(/Internal Server Error/)).toBeTruthy();
    expect(screen.queryByTestId('meter-table')).toBeNull();
    expect(await kpi('kpi-total')).toBe('—');
  });

  it('empty registry: KPIs still render, and there are NO empty chart/table containers', async () => {
    stubApi(defaultRoutes({ '/api/devices/latest': { server_time: DEVICES_LATEST.server_time, devices: [] }, '/api/telemetry': [] }));
    renderAt('/');
    expect(await screen.findByTestId('no-meters')).toBeTruthy();
    expect(await kpi('kpi-total')).toBe('0');
    expect(await kpi('kpi-active')).toBe('0');
    expect(await kpi('kpi-online')).toBe('0');
    expect(await kpi('kpi-delayed')).toBe('0');
    expect(await kpi('kpi-stale')).toBe('0');
    expect(screen.queryByTestId('meter-table')).toBeNull();          // table collapsed to a one-line note
    expect(screen.queryByTestId('site-summary')).toBeNull();
    expect(screen.queryByTestId('status-chart')).toBeNull();
    expect(screen.queryAllByTestId('chartjs-stub')).toHaveLength(0);
  });

  it('shows skeletons while loading', async () => {
    globalThis.fetch = () => new Promise(() => {});
    renderAt('/');
    expect(document.querySelectorAll('.skeleton').length).toBeGreaterThan(0);
  });
});

describe('other routes', () => {
  it('GIS: meters without valid coordinates (NULL or 0,0) are listed, never plotted at a default', async () => {
    stubApi(defaultRoutes({
      '/api/devices/latest': { ...DEVICES_LATEST, devices: DEVICES_LATEST.devices.filter((d) => d.device_id !== 'RTU-001') },
    }));
    renderAt('/gis');
    expect(await screen.findByTestId('gis-empty')).toBeTruthy();
    fireEvent.click(screen.getByText(/No location assigned/));
    const list = screen.getByTestId('no-location-list');
    expect(within(list).getAllByText(/RTU-00/)).toHaveLength(4);   // incl. RTU-005 with 0,0
    expect(document.querySelector('.leaflet-container')).toBeNull();
  });

  it('GIS: filters are staged; nothing is fetched for the heatmap until Apply', async () => {
    const calls = stubApi(defaultRoutes({
      '/api/devices/latest': { ...DEVICES_LATEST, devices: DEVICES_LATEST.devices.filter((d) => d.device_id !== 'RTU-001') },
    }));
    renderAt('/gis');
    await screen.findByTestId('gis-empty');
    fireEvent.change(screen.getByLabelText('View mode'), { target: { value: 'heatmap' } });
    fireEvent.change(screen.getByLabelText('Heatmap period'), { target: { value: '7d' } });
    await new Promise((r) => setTimeout(r, 30));
    expect(calls.some((c) => c.url.startsWith('/api/analytics/heatmap'))).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    await vi.waitFor(() => expect(calls.some((c) => c.url === '/api/analytics/heatmap?period=7d')).toBe(true));
    // no Zone / DMA filters are offered: the registry has no such data
    expect(screen.queryByLabelText(/zone|dma/i)).toBeNull();
  });

  it('GIS: the old /gis-map URL redirects to /gis', async () => {
    stubApi(defaultRoutes());
    renderWithLocation('/gis-map');
    await vi.waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/gis'));
  });

  it('Schematic draws only sites and their registered meters (Devices.SiteId)', async () => {
    stubApi(defaultRoutes());
    renderAt('/schematic');
    expect(await screen.findByTestId('schematic-canvas')).toBeTruthy();
    expect(screen.getByText(/Network: 2 site\(s\), 5 meter\(s\)/)).toBeTruthy();   
    expect(screen.getByText(/Bulk sources, DMAs and consumers are not modelled yet/)).toBeTruthy();
  });

  it('Schematic without registered meters is a compact "not configured" note, not a canvas', async () => {
    stubApi(defaultRoutes({ '/api/devices/latest': { server_time: DEVICES_LATEST.server_time, devices: [] } }));
    renderAt('/schematic');
    expect((await screen.findByTestId('schematic-empty')).textContent).toContain('Schematic data not configured');
    expect(screen.queryByTestId('schematic-canvas')).toBeNull();
  });

  it('retired pages redirect: /maintenance/* and /settings go to Overview', async () => {
    stubApi(defaultRoutes());
    renderWithLocation('/maintenance/RTU-001');
    await vi.waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/'));
  });

  it('unknown routes render the not-found page inside the shell', async () => {
    stubApi(defaultRoutes());
    renderAt('/does/not/exist');
    expect(await screen.findByTestId('page-not-found')).toBeTruthy();
    expect(screen.getByRole('navigation', { name: 'Pages' })).toBeTruthy();
  });
});

describe('navigation', () => {
  it('primary navigation is exactly the six required pages', async () => {
    stubApi(defaultRoutes());
    renderAt('/');
    const nav = await screen.findByRole('navigation', { name: 'Pages' });
    const links = within(nav).getAllByRole('link').map((a) => [a.textContent.trim(), a.getAttribute('href')]);
    expect(links).toEqual([
      ['Overview', '/'], ['DMA Analytics', '/dma-analytics'], ['NRW Analytics', '/nrw-analytics'],
      ['GIS', '/gis'], ['Schematic', '/schematic'], ['Consumer Analytics', '/consumer-analytics'],
    ]);
  });

  it('the former /test-logs URL (and ?tab=mqtt) opens the Testing page', async () => {
    const calls = stubApi(defaultRoutes(TESTING_ROUTES));
    renderAt('/test-logs?tab=mqtt');
    expect(await screen.findByTestId('page-testing')).toBeTruthy();
    await vi.waitFor(() => expect(calls.some((c) => c.url.startsWith('/api/diagnostics/packets?') && c.url.includes('protocol=MQTT'))).toBe(true));
    // dev/KT page: no topbar, no hero, no business navigation
    expect(screen.queryByRole('navigation', { name: 'Pages' })).toBeNull();
    expect(document.querySelector('.storm-topbar')).toBeNull();
    expect(document.querySelector('.storm-hero')).toBeNull();
  });

  it('the old Protocol Test Log API endpoints stay available to the client', async () => {
    const api = await import('./services/stormApi');
    expect(typeof api.fetchDiagnostics).toBe('function');
    expect(typeof api.fetchDiagnostic).toBe('function');
  });
});

const TESTING_ROUTES = {
  '/api/diagnostics/summary': { server_time: '2026-09-25T12:00:00', server_time_display: '25-Sep-2026 12:00:00 IST', window: 'today',
    window_from: null, window_from_display: null, total: 0, valid: 0, unknown_device: 0, invalid: 0, by_protocol: {},
    last_packet_at: null, last_packet_at_display: null, last_packet_protocol: null, services: {}, retention_days: 30 },
  '/api/diagnostics/sources': { server_time: '2026-09-25T12:00:00', server_time_display: '', window: '24h', items: [], truncated: false },
  '/api/diagnostics/packets': { page: 1, page_size: 50, total: 0, total_pages: 1, window: '24h', latest_received_at: null,
    latest_received_at_display: null, server_time: '2026-09-25T12:00:00', server_time_display: '', items: [] },
};

function Where() {
  const l = useLocation();
  return <div data-testid="where">{l.pathname + l.search}</div>;
}

function renderWithLocation(path) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <StormDataProvider refreshMs={0}>
        <AppRoutes />
        <Where />
      </StormDataProvider>
    </MemoryRouter>,
  );
}

describe('Production', () => {
  it('lists only registered meters and selecting one updates the URL', async () => {
    stubApi(defaultRoutes());
    renderWithLocation('/production');
    expect(await screen.findByTestId('production-select-prompt')).toBeTruthy();
    fireEvent.focus(screen.getByRole('combobox', { name: 'Select meter' }));
    const list = await screen.findByRole('listbox', { name: 'Registered meters' });
    const ids = within(list).getAllByRole('option').map((o) => o.dataset.device);
    expect(ids.sort()).toEqual(DEVICES_LATEST.devices.map((d) => d.device_id).sort());
    expect(ids).not.toContain('STRANGER-9');                // unknown senders never become production meters
    fireEvent.change(screen.getByRole('combobox', { name: 'Select meter' }), { target: { value: 'pump' } });
    const option = within(screen.getByRole('listbox')).getByRole('option');
    expect(option.textContent).toContain('Pump House 1');
    fireEvent.mouseDown(option);
    await vi.waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/production?device=RTU-001'));
    expect(await screen.findByTestId('meter-dashboard')).toBeTruthy();
  });

  it('shows the meter dashboard with N/A for NULL values (never 0)', async () => {
    const calls = stubApi(defaultRoutes());
    renderWithLocation('/production?device=RTU-001');
    expect((await screen.findByTestId('meter-name')).textContent).toBe('Pump House 1');
    const kpis = screen.getByTestId('meter-kpis').textContent;
    expect(kpis).toContain('12.50');                          // current flow
    expect(kpis).toContain('100.50');                         // today's total (reading is from today)
    expect(screen.getByTestId('comm-status').textContent).toContain('-71 dBm');
    // READ01 has a value; READ02..05 and pressure are NULL -> hidden until "Show empty fields"
    expect((await screen.findByTestId('additional-data')).textContent).toContain('A1');
    fireEvent.click(screen.getByLabelText(/Show empty fields/));
    const extra = screen.getByTestId('additional-data').textContent;
    expect(extra).toContain('READ02N/A');
    expect(extra).not.toMatch(/READ02\s*0/);
    // only the selected meter's history was requested
    await vi.waitFor(() => expect(calls.some((c) => c.url.startsWith('/api/telemetry/RTU-001?'))).toBe(true));
    expect(calls.some((c) => c.url.startsWith('/api/telemetry?'))).toBe(false);
  });

  it('an unregistered device id is not shown as a production meter', async () => {
    stubApi(defaultRoutes());
    renderWithLocation('/production?device=STRANGER-9');
    expect(await screen.findByTestId('production-not-found')).toBeTruthy();
    expect(screen.queryByTestId('meter-dashboard')).toBeNull();
  });

  it('Open Analytics carries the selected device', async () => {
    stubApi(defaultRoutes());
    renderWithLocation('/production?device=RTU-001');
    const link = await screen.findByTestId('open-analytics');
    expect(link.getAttribute('href')).toBe('/analytics?device=RTU-001');
    fireEvent.click(link);
    await vi.waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/analytics?device=RTU-001'));
    expect((await screen.findByTestId('analytics-meter')).textContent).toBe('Pump House 1');
  });
});

describe('Analytics (device-scoped)', () => {
  it('queries ONLY the selected device and never the fleet endpoint', async () => {
    const calls = stubApi(defaultRoutes());
    renderWithLocation('/analytics?device=RTU-001');
    expect(await screen.findByTestId('device-analytics')).toBeTruthy();
    await vi.waitFor(() => expect(calls.some((c) => c.url.startsWith('/api/telemetry/RTU-001?'))).toBe(true));
    const tele = calls.filter((c) => c.url.startsWith('/api/telemetry'));
    expect(tele.every((c) => c.url.startsWith('/api/telemetry/RTU-001?'))).toBe(true);
    const table = await screen.findByTestId('registers-table');
    expect(within(table).getAllByRole('row')).toHaveLength(3);          // header + 2 readings of RTU-001
    expect(table.textContent).toContain('N/A');                        // NULL registers are N/A
  });

  it('without a meter it asks for one and requests no telemetry', async () => {
    const calls = stubApi(defaultRoutes());
    renderWithLocation('/analytics');
    expect(await screen.findByTestId('analytics-select-prompt')).toBeTruthy();
    await new Promise((r) => setTimeout(r, 30));
    expect(calls.some((c) => c.url.startsWith('/api/telemetry'))).toBe(false);
  });

  it('changing the meter in Analytics updates the URL', async () => {
    stubApi(defaultRoutes({ '/api/telemetry/RTU-003': [] }));
    renderWithLocation('/analytics?device=RTU-001');
    await screen.findByTestId('device-analytics');
    fireEvent.change(screen.getByRole('combobox', { name: 'Select meter' }), { target: { value: 'RTU-003' } });
    fireEvent.mouseDown(within(screen.getByRole('listbox')).getByRole('option'));
    await vi.waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/analytics?device=RTU-003'));
    expect(await screen.findByTestId('analytics-empty')).toBeTruthy();
  });
});

describe('DMA Analytics', () => {
  it('has no DMA data in the registry: compact note, selector disabled, KPIs are dashes, no charts', async () => {
    stubApi(defaultRoutes());
    renderAt('/dma-analytics');
    expect(await screen.findByTestId('dma-not-configured')).toBeTruthy();
    expect(screen.getByLabelText('Select DMA').disabled).toBe(true);
    for (const el of screen.getByTestId('dma-kpis').querySelectorAll('.ov-kpi-value')) expect(el.textContent).toBe('—');
    expect(screen.queryAllByTestId('chartjs-stub')).toHaveLength(0);
    expect(screen.queryByTestId('dma-table')).toBeNull();
  });
});

describe('NRW Analytics', () => {
  it('without bulk/household classification: six KPI cards, 3 periods in the table, all dashes, no charts', async () => {
    stubApi(defaultRoutes());
    renderAt('/nrw-analytics');
    expect(await screen.findByTestId('nrw-kpis')).toBeTruthy();
    expect(screen.getByTestId('nrw-kpis').children).toHaveLength(6);
    for (const el of screen.getByTestId('nrw-kpis').querySelectorAll('.nrw-kpi-value')) expect(el.textContent).toBe('—');
    expect(screen.getByTestId('nrw-not-configured')).toBeTruthy();
    expect(screen.queryByTestId('nrw-charts')).toBeNull();
    const rows = within(screen.getByTestId('nrw-table')).getAllByRole('row');
    expect(rows).toHaveLength(4);                                        // header + Current Day / 7 Days / 30 Days
    expect(rows.slice(1).map((r) => r.querySelector('td').textContent)).toEqual(['Current Day', 'Last 7 Days', 'Last 30 Days']);
    expect(document.body.textContent).not.toMatch(/NaN|Infinity/);
  });
});

describe('Consumer Analytics', () => {
  it('before a meter is selected: one compact prompt, no charts, no analytics requests', async () => {
    const calls = stubApi(defaultRoutes());
    renderWithLocation('/consumer-analytics');
    expect((await screen.findByTestId('consumer-select-prompt')).textContent).toBe('Search and select a meter to view historical consumption.');
    expect(screen.queryAllByTestId('chartjs-stub')).toHaveLength(0);
    await new Promise((r) => setTimeout(r, 30));
    expect(calls.some((c) => c.url.startsWith('/api/analytics/devices'))).toBe(false);
    expect(calls.some((c) => c.url.startsWith('/api/telemetry'))).toBe(false);
  });

  it('search finds registered meters by name, device id and IMEI; choosing one puts it in the URL', async () => {
    stubApi(defaultRoutes());
    renderWithLocation('/consumer-analytics');
    const box = await screen.findByRole('combobox', { name: 'Select meter' });
    fireEvent.focus(box);
    fireEvent.change(box, { target: { value: 'pump' } });
    expect(within(screen.getByRole('listbox')).getAllByRole('option')).toHaveLength(1);
    fireEvent.change(box, { target: { value: 'RTU-003' } });
    expect(within(screen.getByRole('listbox')).getAllByRole('option')).toHaveLength(1);
    fireEvent.change(box, { target: { value: '860000000000000' } });
    expect(within(screen.getByRole('listbox')).getAllByRole('option').length).toBeGreaterThan(1);
    fireEvent.change(box, { target: { value: 'pump' } });
    fireEvent.mouseDown(within(screen.getByRole('listbox')).getByRole('option'));
    await vi.waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/consumer-analytics?device=RTU-001'));
    expect(await screen.findByTestId('meter-analytics')).toBeTruthy();
  });

  it('selected meter: header, 24h / yesterday / last-month comparison, bar chart, trend and history', async () => {
    const calls = stubApi(defaultRoutes());
    renderWithLocation('/consumer-analytics?device=RTU-001');
    expect((await screen.findByTestId('ca-meter-id')).textContent).toBe('RTU-001');
    expect(screen.getByTestId('ca-meter-name').textContent).toBe('Pump House 1');
    expect(await screen.findByTestId('period-last_24h-value')).toBeTruthy();
    expect(screen.getByTestId('period-last_24h-value').textContent).toBe('10.00 KL');
    expect(screen.getByTestId('period-yesterday-value').textContent).toBe('24.00 KL');
    expect(screen.getByTestId('period-last_month-value').textContent).toBe('620.00 KL');
    expect(screen.getByTestId('period-last_month').textContent).toContain('Last month (Aug 2026)');
    expect(screen.getByTestId('period-yesterday').textContent).toMatch(/Peak flow\s*11\.00 m3\/h/);
    expect(await screen.findByTestId('compare-chart')).toBeTruthy();
    expect(await screen.findByTestId('trend-chart')).toBeTruthy();
    const table = await screen.findByTestId('history-table');
    expect(within(table).getAllByRole('row')).toHaveLength(3);
    expect(table.textContent).toContain('—');                            // NULL battery is a dash, not 0
    expect(screen.getByTestId('history-page').textContent).toBe('Page 1 / 2');
    expect(calls.every((c) => c.method === 'GET')).toBe(true);
    // 5000 raw rows are never pulled for this page: trend is bucketed and history is paginated server-side
    expect(calls.some((c) => c.url.startsWith('/api/telemetry'))).toBe(false);
    expect(calls.some((c) => c.url === '/api/analytics/devices/RTU-001/trend?window=24h')).toBe(true);
    expect(calls.some((c) => c.url.startsWith('/api/analytics/devices/RTU-001/history?page=1&page_size=50'))).toBe(true);
  });

  it('trend window and history pagination refetch from the server', async () => {
    const calls = stubApi(defaultRoutes({ '/api/analytics/devices/RTU-001/trend': (u) => ({ ...CONSUMPTION_RTU001, device_id: 'RTU-001', window: u.split('window=')[1], bucket_minutes: 360, flow_unit: 'm3/h', points: [] }) }));
    renderWithLocation('/consumer-analytics?device=RTU-001');
    await screen.findByTestId('history-table');
    fireEvent.change(screen.getByLabelText('Trend window'), { target: { value: '7d' } });
    await vi.waitFor(() => expect(calls.some((c) => c.url === '/api/analytics/devices/RTU-001/trend?window=7d')).toBe(true));
    expect(await screen.findByTestId('trend-chart-empty')).toBeTruthy();  // compact note, not a blank chart
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
    await vi.waitFor(() => expect(calls.some((c) => c.url.startsWith('/api/analytics/devices/RTU-001/history?page=2'))).toBe(true));
  });

  it('a meter whose unit cannot be converted is reported, never converted silently', async () => {
    const bad = { ...CONSUMPTION_RTU001, periods: CONSUMPTION_RTU001.periods.map((p) => ({ ...p, consumption_kl: null, unit_convertible: false, total_unit: 'gal' })) };
    stubApi(defaultRoutes({ '/api/analytics/devices/RTU-001/consumption': bad }));
    renderWithLocation('/consumer-analytics?device=RTU-001');
    expect((await screen.findByTestId('period-last_24h')).textContent).toContain('Unit gal cannot be converted to KL');
    expect(screen.getByTestId('period-last_24h-value').textContent).toBe('—');
    expect(screen.queryByTestId('compare-chart')).toBeNull();
    expect(screen.getByTestId('compare-chart-empty')).toBeTruthy();
  });

  it('a meter with no telemetry shows compact notes, not blank containers', async () => {
    const none = { ...CONSUMPTION_RTU001, flow_unit: null, periods: CONSUMPTION_RTU001.periods.map((p) => ({ ...p, consumption_kl: null, consumption_raw: null, total_unit: null, flow_avg: null, flow_max: null, flow_min: null, readings: 0 })) };
    stubApi(defaultRoutes({ '/api/analytics/devices/RTU-001/consumption': none, '/api/analytics/devices/RTU-001/trend': { ...CONSUMPTION_RTU001, window: '24h', bucket_minutes: 60, flow_unit: null, points: [] },
      '/api/analytics/devices/RTU-001/history': { ...HISTORY_RTU001, total: 0, items: [] } }));
    renderWithLocation('/consumer-analytics?device=RTU-001');
    expect((await screen.findByTestId('period-last_24h')).textContent).toContain('No readings in this period');
    expect(await screen.findByTestId('history-empty')).toBeTruthy();
    expect(screen.queryAllByTestId('chartjs-stub')).toHaveLength(0);
  });

  it('an unregistered meter id is not analysed', async () => {
    const calls = stubApi(defaultRoutes());
    renderWithLocation('/consumer-analytics?device=STRANGER-9');
    expect(await screen.findByTestId('consumer-not-found')).toBeTruthy();
    expect(calls.some((c) => c.url.includes('STRANGER-9'))).toBe(false);
  });
});
