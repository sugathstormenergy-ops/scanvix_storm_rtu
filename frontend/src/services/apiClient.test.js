import { describe, expect, it } from 'vitest';
import { apiGet, ApiError } from './apiClient';
import { stubApi } from '../test/fixtures';

describe('apiClient', () => {
  it('uses same-origin relative URLs, GET, no-store', async () => {
    const calls = stubApi({ '/api/devices/latest': { ok: 1 } });
    await expect(apiGet('/api/devices/latest')).resolves.toEqual({ ok: 1 });
    expect(calls).toEqual([{ url: '/api/devices/latest', method: 'GET' }]);
  });
  it('encodes query params and drops empty ones', async () => {
    const calls = stubApi({ '/api/telemetry': [] });
    await apiGet('/api/telemetry', { params: { from: '2026-09-25T00:00:00', device_id: undefined, limit: 5000, x: '' } });
    expect(calls[0].url).toBe('/api/telemetry?from=2026-09-25T00%3A00%3A00&limit=5000');
  });
  it('throws ApiError with status on HTTP errors and does NOT retry or substitute data', async () => {
    const calls = stubApi({ '/api/devices/latest': { httpStatus: 503, body: { detail: 'Database unavailable' } } });
    const err = await apiGet('/api/devices/latest').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(503);
    expect(err.message).toContain('Database unavailable');
    expect(calls).toHaveLength(1);
  });
  it('retries once on a network error, then throws', async () => {
    const calls = stubApi({ '/health': new TypeError('Failed to fetch') });
    const err = await apiGet('/health').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toBe('Cannot reach the Storm RTU server');
    expect(calls).toHaveLength(2);
  });
  it('refuses absolute or non-API URLs', async () => {
    stubApi({});
    await expect(apiGet('http://evil.example/api/x')).rejects.toThrow(/Refusing/);
    await expect(apiGet('/index.html')).rejects.toThrow(/Refusing/);
  });
  it('rejects invalid JSON bodies instead of returning partial data', async () => {
    globalThis.fetch = async () => new Response('<html>', { status: 200 });
    await expect(apiGet('/api/devices/latest')).rejects.toThrow(/invalid response/);
  });
});
