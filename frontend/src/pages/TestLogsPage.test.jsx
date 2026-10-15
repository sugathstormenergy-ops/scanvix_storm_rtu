import { describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import TestLogsPage, { REFRESH_MS } from './TestLogsPage';
import { stubApi } from '../test/fixtures';
import { formatIstMs, makeAnchor, serverNowFromAnchor } from '../utils/serverClock';

const item = (over) => ({
  id: 1, received_at: '2026-09-25T17:35:37', received_at_display: '25-Sep-2026 17:35:37 IST', protocol: 'TCP',
  status: 'VALID', outcome: 'PROCESSED', source_ip: '192.168.0.77', device_id: 'RTU-1', device_name: 'Pump 1',
  imei: '860000000000001', site_id: 'SITE-A', is_registered: true, topic: null, qos: null,
  payload_preview: '{"deviceId":"RTU-1"}', payload_encoding: 'TEXT', payload_bytes: 20, payload_truncated: false,
  error_reason: null, ...over,
});

const page = (items, over = {}) => ({
  protocol: 'TCP', page: 1, page_size: 50, total: items.length, total_pages: 1,
  latest_received_at: '2026-09-25T17:35:37', latest_received_at_display: '25-Sep-2026 17:35:37 IST',
  server_time: '2026-09-25T17:35:42', server_time_display: '25-Sep-2026 17:35:42 IST', retention_days: 30,
  items, ...over,
});

const TCP_ITEMS = [
  item({ id: 3 }),
  item({ id: 2, status: 'UNKNOWN_DEVICE', outcome: 'UNKNOWN_DEVICE', device_id: 'STRANGER-9', device_name: null, imei: null, site_id: 'X', is_registered: false }),
  item({ id: 1, status: 'INVALID', outcome: 'PARSE_ERROR', device_id: null, device_name: null, imei: null, site_id: null,
    payload_preview: '<script>alert(1)</script>', error_reason: 'MALFORMED_PACKET: No TCP parser could handle packet' }),
];

function renderAt(path = '/test-logs') {
  return render(<MemoryRouter initialEntries={[path]}><TestLogsPage /></MemoryRouter>);
}

describe('Protocol Test Log page', () => {
  it('defaults to TCP and renders the required columns and statuses', async () => {
    const calls = stubApi({ '/api/diagnostics/tcp': page(TCP_ITEMS) });
    renderAt();
    const table = await screen.findByTestId('tlog-table');
    await within(table).findByText('Pump 1');
    expect(screen.getByText('STORM ENERGY RTU — TCP TEST LOG')).toBeTruthy();
    const heads = within(table).getAllByRole('columnheader').map((h) => h.textContent);
    expect(heads).toEqual(['Received Time', 'Device', 'IMEI', 'Site ID', 'Source IP', 'Protocol', 'Status', 'Payload']);
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows.map((r) => r.querySelector('[data-status]').dataset.status)).toEqual(['VALID', 'UNKNOWN_DEVICE', 'INVALID']);
    // invalid packet: Device UNKNOWN, IMEI and Site ID "—"
    const cells = within(rows[2]).getAllByRole('cell').map((c) => c.textContent);
    expect(cells.slice(1, 4)).toEqual(['UNKNOWN', '—', '—']);
    expect(within(rows[1]).getByText('UNKNOWN DEVICE')).toBeTruthy();
    expect(screen.getByTestId('tlog-total').textContent).toBe('3');
    expect(screen.getByTestId('tlog-last').textContent).toBe('25-Sep-2026 17:35:37 IST');
    expect(calls[0].url).toBe('/api/diagnostics/tcp?page=1&page_size=50');
    expect(calls.every((c) => c.method === 'GET')).toBe(true);
  });

  it('renders payloads as text only (no HTML injection)', async () => {
    stubApi({ '/api/diagnostics/tcp': page(TCP_ITEMS) });
    renderAt();
    await screen.findByText('<script>alert(1)</script>');
    expect(document.querySelector('[data-testid="page-test-logs"] script')).toBeNull();
  });

  it('shows the server time, not the browser clock', async () => {
    vi.spyOn(Date, 'now').mockReturnValue(Date.UTC(2031, 0, 1, 3, 4, 5));   // wildly wrong browser clock
    stubApi({ '/api/diagnostics/tcp': page(TCP_ITEMS) });
    renderAt();
    await screen.findByText('Pump 1');
    const shown = await screen.findByTestId('tlog-server-time');
    expect(shown.textContent).toMatch(/^25-Sep-2026 17:35:4\d IST$/);
  });

  it('MQTT tab uses the MQTT endpoint and shows topic columns', async () => {
    const calls = stubApi({
      '/api/diagnostics/mqtt': page([item({ protocol: 'MQTT', topic: 'storm/meters/RTU-1/telemetry', qos: 1, source_ip: null })], { protocol: 'MQTT' }),
    });
    renderAt('/test-logs?tab=mqtt');
    const table = await screen.findByTestId('tlog-table');
    await within(table).findByText('storm/meters/RTU-1/telemetry');
    expect(within(table).getAllByRole('columnheader').map((h) => h.textContent))
      .toEqual(['Received Time', 'Device', 'Device ID', 'Topic', 'Source', 'Protocol', 'Status', 'Payload']);
    expect(screen.getByText('STORM ENERGY RTU — MQTT TEST LOG')).toBeTruthy();
    expect(calls[0].url.startsWith('/api/diagnostics/mqtt?')).toBe(true);
  });

  it('paginates and changes page size server-side', async () => {
    const calls = stubApi({ '/api/diagnostics/tcp': (url) => page(TCP_ITEMS, { total: 120, total_pages: 3, page: Number(new URL(url, 'http://x').searchParams.get('page')) }) });
    renderAt();
    await screen.findByText('Pump 1');
    fireEvent.click(screen.getByRole('button', { name: /NEXT/ }));
    await screen.findByText('Page 2 of 3');
    expect(calls.at(-1).url).toBe('/api/diagnostics/tcp?page=2&page_size=50');
    fireEvent.change(screen.getByLabelText('Rows per page'), { target: { value: '100' } });
    await vi.waitFor(() => expect(calls.at(-1).url).toBe('/api/diagnostics/tcp?page=1&page_size=100'));
  });

  it('applies filters as query parameters', async () => {
    const calls = stubApi({ '/api/diagnostics/tcp': page(TCP_ITEMS) });
    renderAt();
    await screen.findByText('Pump 1');
    fireEvent.change(screen.getByLabelText('Status filter'), { target: { value: 'INVALID' } });
    fireEvent.change(screen.getByLabelText('Source IP filter'), { target: { value: '192.168.0.' } });
    fireEvent.click(screen.getByRole('button', { name: 'APPLY' }));
    await vi.waitFor(() => expect(calls.at(-1).url).toBe('/api/diagnostics/tcp?page=1&page_size=50&source_ip=192.168.0.&status=INVALID'));
  });

  it('auto-refreshes every 5 s after the previous request completes', async () => {
    vi.useFakeTimers();
    try {
      const calls = stubApi({ '/api/diagnostics/tcp': page(TCP_ITEMS) });
      renderAt();
      await act(async () => { await vi.advanceTimersByTimeAsync(10); });
      expect(calls).toHaveLength(1);
      await act(async () => { await vi.advanceTimersByTimeAsync(REFRESH_MS - 100); });
      expect(calls).toHaveLength(1);
      await act(async () => { await vi.advanceTimersByTimeAsync(200); });
      expect(calls).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it('opens the complete payload of one record', async () => {
    const full = '<b>bold?</b>' + 'X'.repeat(500);
    stubApi({
      '/api/diagnostics/tcp': page(TCP_ITEMS),
      '/api/diagnostics/tcp/1': { ...TCP_ITEMS[2], payload: full },
    });
    renderAt();
    fireEvent.click(await screen.findByText('<script>alert(1)</script>'));
    const pre = await screen.findByTestId('tlog-payload-full');
    expect(pre.textContent).toBe(full);
    expect(pre.querySelector('b')).toBeNull();
  });

  it('shows an error without inventing data', async () => {
    stubApi({ '/api/diagnostics/tcp': { httpStatus: 500, body: { detail: 'Internal Server Error' } } });
    renderAt();
    expect(await screen.findByText(/Cannot load the TCP test log/)).toBeTruthy();
    expect(within(screen.getByTestId('tlog-table')).getAllByRole('row')).toHaveLength(1);
  });
});

describe('server clock', () => {
  it('formats IST wall-clock values without the browser timezone', () => {
    expect(formatIstMs(Date.UTC(2026, 8, 25, 17, 35, 42))).toBe('25-Sep-2026 17:35:42 IST');
  });
  it('advances from the server anchor with a monotonic clock', () => {
    const a = makeAnchor('2026-09-25T17:35:42', 1000);
    expect(formatIstMs(serverNowFromAnchor(a, 4000))).toBe('25-Sep-2026 17:35:45 IST');
    expect(makeAnchor(null, 0)).toBeNull();
  });
});
