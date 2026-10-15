import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import TestingPage from './TestingPage';
import { TELEMETRY_ROWS } from '../utils/testingModel';
import { stubApi } from '../test/fixtures';

const SUMMARY = {
  server_time: '2026-09-29T10:25:20', server_time_display: '29-Sep-2026 10:25:20 IST', window: 'today',
  window_from: '2026-09-29T00:00:00', window_from_display: '29-Sep-2026 00:00:00 IST',
  total: 3, valid: 1, unknown_device: 1, invalid: 1,
  by_protocol: { TCP: { total: 2, VALID: 0, UNKNOWN_DEVICE: 1, INVALID: 1 }, MQTT: { total: 1, VALID: 1, UNKNOWN_DEVICE: 0, INVALID: 0 } },
  last_packet_at: '2026-09-29T10:25:14', last_packet_at_display: '29-Sep-2026 10:25:14 IST', last_packet_protocol: 'MQTT',
  services: {
    api: { status: 'ok', details: 'version 1.0.0' }, database: { status: 'ok', details: 'SQL Server reachable' },
    mqtt_broker: { status: 'ok', details: 'Broker connected' }, tcp_listener: { status: 'ok', details: 'listening' },
  },
  retention_days: 30,
};

const src = (over) => ({
  key: 'MQTT:864857030195695', protocol: 'MQTT', protocol_label: 'MQTT / JSON', device_id: '864857030195695',
  device_name: 'Narsapur Town', imei: '864857030195695', site_id: 'BENCH', source_ip: null,
  topic: 'storm/meters/864857030195695/telemetry', is_registered: true, device_is_active: true,
  device_last_seen_at: '2026-09-29T10:25:14', last_seen_at: '2026-09-29T10:25:14',
  last_seen_at_display: '29-Sep-2026 10:25:14 IST', last_status: 'VALID', last_result: 'PROCESSED', packet_count: 12,
  last_flow: 18.42, last_flow_unit: 'm3/h', last_total_today: 324.81, last_signal_dbm: -71, last_packet_id: 3, ...over,
});
const SOURCES = {
  server_time: SUMMARY.server_time, server_time_display: SUMMARY.server_time_display, window: '24h', truncated: false,
  items: [
    src(),
    src({ key: 'TCP:STRANGER-9', protocol: 'TCP', protocol_label: 'TCP / ASCII', device_id: 'STRANGER-9', device_name: null, imei: null,
      site_id: 'X', source_ip: '10.1.1.5', topic: null, is_registered: false, device_is_active: null, device_last_seen_at: null,
      last_status: 'UNKNOWN_DEVICE', last_result: 'UNKNOWN_DEVICE', packet_count: 2, last_flow: 3.2, last_total_today: 44 }),
    src({ key: 'TCP:45.79.115.134', protocol: 'TCP', protocol_label: 'TCP / ASCII', device_id: null, device_name: null, imei: null,
      site_id: null, source_ip: '45.79.115.134', topic: null, is_registered: false, device_is_active: null,
      device_last_seen_at: null, last_status: 'INVALID', last_result: 'PARSE_ERROR', packet_count: 1, last_flow: null,
      last_total_today: null, last_signal_dbm: null }),
  ],
};

const pkt = (over) => ({
  id: 3, received_at: '2026-09-29T10:25:14', received_at_display: '29-Sep-2026 10:25:14 IST', protocol: 'MQTT',
  protocol_label: 'MQTT / JSON', status: 'VALID', outcome: 'PROCESSED', device_id: '864857030195695', device_name: null,
  imei: '864857030195695', site_id: 'BENCH', source_ip: null, topic: 'storm/meters/864857030195695/telemetry', qos: 1,
  size: 310, flow: 18.42, flow_unit: 'm3/h', total_today: 324.81, error_reason: null, payload_encoding: 'TEXT',
  payload_preview: '{"deviceId":"864857030195695"}', ...over,
});
const PACKETS = {
  page: 1, page_size: 50, total: 3, total_pages: 1, window: '24h',
  latest_received_at: '2026-09-29T10:25:14', latest_received_at_display: '29-Sep-2026 10:25:14 IST',
  server_time: SUMMARY.server_time, server_time_display: SUMMARY.server_time_display,
  items: [
    pkt(),
    pkt({ id: 2, protocol: 'TCP', protocol_label: 'TCP / ASCII', status: 'UNKNOWN_DEVICE', outcome: 'UNKNOWN_DEVICE',
      device_id: 'STRANGER-9', imei: null, site_id: 'X', source_ip: '10.1.1.5', topic: null, qos: null, size: 120,
      flow: 3.2, total_today: 44, received_at_display: '29-Sep-2026 10:24:00 IST' }),
    pkt({ id: 1, protocol: 'TCP', protocol_label: 'TCP / ASCII', status: 'INVALID', outcome: 'PARSE_ERROR', device_id: null,
      imei: null, site_id: null, source_ip: '45.79.115.134', topic: null, qos: null, size: 58, flow: null, total_today: null,
      payload_encoding: 'HEX', payload_preview: '16 03 01', received_at_display: '29-Sep-2026 10:22:13 IST',
      error_reason: 'MALFORMED_PACKET: No TCP parser could handle packet from 45.79.115.134 (58 bytes)' }),
  ],
};

const HEX58 = Array.from({ length: 58 }, (_, i) => (i < 3 ? ['16', '03', '01'][i] : '00')).join(' ');
const DETAIL_INVALID = {
  ...PACKETS.items[2], server_time: SUMMARY.server_time, server_time_display: SUMMARY.server_time_display, is_registered: false,
  transport_received: 'YES - received by the TCP listener', parse_status: 'REJECTED',
  database_status: 'NOT STORED - parse error', acknowledgement: 'none sent - NullAck (no acknowledgement — TBD with Scanvix)',
  raw_message_id: 901, telemetry_id: null, payload_format: 'BINARY', payload_complete: true, payload_text: null,
  payload_escaped: '\\x16\\x03\\x01' + '\\x00'.repeat(55), payload_hex: HEX58, telemetry: null, decoded_json: null,
  field_check: null, reparse_error: null,
};
const TELEMETRY = {
  device_id: '864857030195695', site_id: 'BENCH', timestamp: '2026-09-29 10:25:10', flow: 18.42, flow_unit: 'm3/h',
  total_today: 324.81, total_yesterday: null, sensor_type: 'rs485', signal_dbm: -71, battery: null, fw_version: '1.0.0',
  read01: '000000', read02: null, read03: null, read04: null, read05: null, pressure: null,
};
const DETAIL_VALID = {
  ...PACKETS.items[0], server_time: SUMMARY.server_time, server_time_display: SUMMARY.server_time_display, is_registered: true,
  transport_received: 'YES - delivered by the MQTT broker', parse_status: 'ACCEPTED', database_status: 'STORED - telemetry row 77',
  acknowledgement: 'MQTT QoS 1 - acknowledged by the broker', raw_message_id: 903, telemetry_id: 77, payload_format: 'JSON',
  payload_complete: true, payload_text: '{"deviceId":"864857030195695","PRESSURE":null,"PRESSURE":null,"x":"<b>hi</b>"}',
  payload_escaped: '{"deviceId":"864857030195695"}', payload_hex: '7B 22', telemetry: TELEMETRY, decoded_json: {},
  field_check: {
    fields: [{ field: 'deviceId', required: true, present: true, key: 'deviceId', is_null: false, value: '864857030195695' },
      { field: 'battery', required: false, present: false, key: null, is_null: false, value: null },
      { field: 'PRESSURE', required: false, present: true, key: 'PRESSURE', is_null: true, value: null }],
    undocumented_keys: ['x'], duplicate_keys: ['PRESSURE'], missing_required: [],
  },
  reparse_error: null,
};

function Loc() { return <div data-testid="loc">{useLocation().pathname + useLocation().search}</div>; }

function renderAt(path = '/testing') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes><Route path="/testing" element={<><TestingPage /><Loc /></>} /></Routes>
    </MemoryRouter>,
  );
}

function routes(over = {}) {
  return {
    '/api/diagnostics/summary': SUMMARY, '/api/diagnostics/sources': SOURCES, '/api/diagnostics/packets': PACKETS,
    '/api/diagnostics/packets/1': DETAIL_INVALID, '/api/diagnostics/packets/3': DETAIL_VALID, ...over,
  };
}

describe('Testing page', () => {
  it('compact console: no topbar/hero, protocol tabs drive the packets API, states are distinguishable', async () => {
    const calls = stubApi(routes());
    renderAt();
    const table = await screen.findByTestId('packet-table');
    await within(table).findByText('45.79.115.134');
    expect(document.querySelector('.storm-topbar')).toBeNull();
    expect(document.querySelector('.storm-hero')).toBeNull();
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Testing / Protocol Diagnostics');
    const tabs = screen.getAllByRole('tab').map((t) => t.textContent);
    expect(tabs).toEqual(['TCP', 'MQTT', 'Packets']);
    // invalid / unknown / parse-error packets are never hidden
    const badges = [...table.querySelectorAll('.tlog-badge')].map((b) => b.textContent);
    expect(badges).toEqual(expect.arrayContaining(['VALID', 'UNKNOWN', 'PARSE ERROR']));
    fireEvent.click(screen.getByRole('tab', { name: 'MQTT' }));
    await vi.waitFor(() => expect(calls.some((c) => c.url.startsWith('/api/diagnostics/packets?') && c.url.includes('protocol=MQTT'))).toBe(true));
    expect(screen.getByRole('tab', { name: 'MQTT' }).getAttribute('aria-selected')).toBe('true');
    fireEvent.click(screen.getByRole('tab', { name: 'Packets' }));
    await vi.waitFor(() => expect(calls.filter((c) => c.url.startsWith('/api/diagnostics/packets?')).at(-1).url).not.toContain('protocol='));
  });

  it('status bar shows server time, services and counts', async () => {
    stubApi(routes());
    renderAt();
    await screen.findByTestId('packet-table');
    expect((await screen.findByTestId('server-time')).textContent).toMatch(/^29-Sep-2026 10:25:2\d IST$/);
    expect(screen.getByTestId('count-total').textContent).toBe('3');
    expect(screen.getByTestId('count-valid').textContent).toBe('1');
    expect(screen.getByTestId('count-unknown').textContent).toBe('1');
    expect(screen.getByTestId('count-invalid').textContent).toBe('1');
    expect(screen.getByTestId('last-packet').textContent).toBe('29-Sep-2026 10:25:14 IST · MQTT');
    const bar = screen.getByTestId('status-bar').textContent;
    for (const s of ['TCP listener', 'MQTT broker', 'API', 'Database']) expect(bar).toContain(s);
  });

  it('stream shows TCP and MQTT, VALID, UNKNOWN_DEVICE and INVALID with the required columns', async () => {
    stubApi(routes());
    renderAt();
    const table = await screen.findByTestId('packet-table');
    await within(table).findByText('45.79.115.134');
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent))
      .toEqual(['TIME', 'PROTOCOL', 'DEVICE', 'SITE', 'SOURCE', 'STATUS', 'SIZE', 'FLOW', 'TODAY', 'RESULT']);
    const rows = within(table).getAllByRole('row').slice(1);
    const cells = (r) => within(r).getAllByRole('cell').map((c) => c.textContent);
    expect(cells(rows[0]).slice(0, 9)).toEqual(['29-Sep-2026 10:25:14 IST', 'MQTT / JSON', '864857030195695', 'BENCH', 'broker', 'VALID', '310 bytes', '18.42', '324.81']);
    expect(cells(rows[1])[5]).toBe('UNKNOWN');
    expect(cells(rows[2]).slice(0, 9)).toEqual(['29-Sep-2026 10:22:13 IST', 'TCP / ASCII', 'UNKNOWN', '—', '45.79.115.134', 'PARSE ERROR', '58 bytes', '—', '—']);
    expect(cells(rows[2])[9]).toContain('No TCP parser could handle packet from 45.79.115.134 (58 bytes)');
  });

  it('device/source summary keeps unknown devices and invalid sources visible', async () => {
    stubApi(routes());
    renderAt();
    const t = await screen.findByTestId('sources-table');
    await within(t).findByText('Narsapur Town');
    const status = (key) => t.querySelector(`tr[data-key="${key}"] .tst-st`).dataset.status;
    expect(status('MQTT:864857030195695')).toBe('online');
    expect(status('TCP:STRANGER-9')).toBe('unknown');
    expect(status('TCP:45.79.115.134')).toBe('unknown');
    expect(t.querySelector('tr[data-key="TCP:45.79.115.134"] td').textContent).toBe('UNKNOWN');
  });

  it('invalid binary packet detail shows raw hex, escaped bytes and the exact error', async () => {
    stubApi(routes());
    renderAt();
    fireEvent.click(await within(await screen.findByTestId('packet-table')).findByText('45.79.115.134'));
    const panel = await screen.findByTestId('packet-detail');
    await within(panel).findByText('REJECTED');
    expect(within(panel).getByTestId('hex-payload').textContent).toBe(HEX58);
    expect(within(panel).getByTestId('hex-payload').textContent.split(' ')).toHaveLength(58);
    expect(within(panel).getByTestId('escaped-payload').textContent.startsWith('\\x16\\x03\\x01\\x00')).toBe(true);
    expect(within(panel).getByTestId('error-message').textContent)
      .toBe('MALFORMED_PACKET: No TCP parser could handle packet from 45.79.115.134 (58 bytes)');
    expect(within(panel).getByTestId('raw-payload').textContent).toMatch(/Binary/);
    expect(panel.textContent).toContain('NOT STORED - parse error');
    expect(panel.textContent).toContain('none sent - NullAck');
  });

  it('valid packet detail: parsed fields with N/A for NULL, raw payload as text, duplicate key warning', async () => {
    stubApi(routes());
    renderAt();
    const table = await screen.findByTestId('packet-table');
    fireEvent.click(await within(table).findByText('310 bytes'));
    const panel = await screen.findByTestId('packet-detail');
    const parsed = await within(panel).findByTestId('parsed-telemetry');
    const rows = [...parsed.children];
    const value = (label) => rows[rows.findIndex((el) => el.textContent === label) + 1].textContent;
    expect(rows.filter((_, i) => i % 2 === 0).map((el) => el.textContent)).toEqual(TELEMETRY_ROWS.map(([, l]) => l));
    expect(value('Flow')).toBe('18.42');
    expect(value('Battery')).toBe('N/A');                 // NULL is not shown as 0
    expect(value('Yesterday Total')).toBe('N/A');
    expect(value('Pressure')).toBe('N/A');
    expect(value('READ01')).toBe('000000');
    expect(within(panel).getByTestId('raw-payload').textContent).toBe(DETAIL_VALID.payload_text);
    expect(panel.querySelector('b')).toBeNull();              // payload text never becomes markup
    expect(within(panel).getByTestId('duplicate-keys').textContent).toContain('PRESSURE');
    expect(within(panel).getByTestId('field-check').textContent).toContain('deviceId *');
  });

  it('filters and refresh settings drive the API query', async () => {
    const calls = stubApi(routes());
    renderAt('/testing?device=864857030195695&protocol=mqtt');
    await screen.findByTestId('packet-table');
    const first = calls.find((c) => c.url.startsWith('/api/diagnostics/packets?'));
    expect(first.url).toContain('protocol=MQTT');
    expect(first.url).toContain('device_id=864857030195695');
    fireEFilter();
    await screen.findByTestId('packet-table');
    await new Promise((r) => setTimeout(r, 20));
    const last = calls.filter((c) => c.url.startsWith('/api/diagnostics/packets?')).at(-1);
    expect(last.url).toContain('status=INVALID');
    expect(last.url).toContain('window=1h');
    expect(calls.every((c) => c.method === 'GET')).toBe(true);
  });

  it('clicking a source filters the stream to it', async () => {
    const calls = stubApi(routes());
    renderAt();
    const t = await screen.findByTestId('sources-table');
    fireEvent.click(await within(t).findByText('45.79.115.134'));
    await new Promise((r) => setTimeout(r, 20));
    const last = calls.filter((c) => c.url.startsWith('/api/diagnostics/packets?')).at(-1);
    expect(last.url).toContain('protocol=TCP');
    expect(last.url).toContain('source_ip=45.79.115.134');
  });

  it('API failure is shown, never replaced by invented data', async () => {
    stubApi(routes({ '/api/diagnostics/packets': { httpStatus: 500, body: { detail: 'Internal Server Error' } } }));
    renderAt();
    expect(await screen.findByText(/Cannot load test data/)).toBeTruthy();
    expect(within(screen.getByTestId('packet-table')).getAllByRole('row')).toHaveLength(1);
  });
});

function fireEFilter() {
  fireEvent.change(screen.getByLabelText('Status filter'), { target: { value: 'INVALID' } });
  fireEvent.change(screen.getByLabelText('Time window'), { target: { value: '1h' } });
}
