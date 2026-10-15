/**
 * TEST-ONLY end-to-end smoke test (Chromium via playwright-core) against the production
 * build served through the production nginx configs (see e2e/proxy-harness.sh) and the
 * fixture API (e2e/fixture_api.py <port> <tcp_port>).
 *
 *   npm i --no-save playwright-core
 *   E2E_BASE=https://127.0.0.1:19443 E2E_TCP_PORT=18100 node e2e/smoke.mjs   # normal run
 *   E2E_BASE=https://127.0.0.1:19443 node e2e/smoke.mjs api-down   # with the API stopped
 *
 * Screenshots are written to e2e-results/ (git- and docker-ignored).
 */
import { chromium } from 'playwright-core';
import { mkdirSync } from 'node:fs';
import assert from 'node:assert/strict';
import net from 'node:net';

const BASE = process.env.E2E_BASE || 'https://127.0.0.1:19443';
const MODE = process.argv[2] || 'normal';
const OUT = new URL('../e2e-results/', import.meta.url).pathname;
const TILE_HOSTS = /(^|\.)tile\.openstreetmap\.org$|^server\.arcgisonline\.com$/;
mkdirSync(OUT, { recursive: true });

const executablePath = process.env.CHROMIUM_PATH || undefined;
const browser = await chromium.launch({ executablePath, args: ['--ignore-certificate-errors'] });
const context = await browser.newContext({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 900 } });

const requests = [];
const pageErrors = [];
context.on('request', (r) => requests.push({ url: r.url(), method: r.method() }));
// Tiles are fetched from the Internet by the browser; the sandbox may block them. They are
// optional (markers do not depend on them), so abort them to keep the run deterministic.
await context.route((url) => TILE_HOSTS.test(url.hostname), (route) => route.abort());

const results = [];
async function step(name, fn) {
  const page = await context.newPage();
  page.on('pageerror', (e) => pageErrors.push(`${name}: ${e.message}`));
  try {
    await fn(page);
    results.push([name, 'PASS']);
  } catch (e) {
    results.push([name, `FAIL: ${e.message.split('\n').filter(Boolean).slice(0, 4).join(' | ')}`]);
    await page.screenshot({ path: `${OUT}FAIL-${name.replace(/\W+/g, '_')}.png`, fullPage: true }).catch(() => {});
  } finally {
    await page.close();
  }
}
const kpi = (page, id) => page.locator(`[data-testid="${id}"] .ov-kpi-value`).innerText();

async function httpGet(path) {
  const r = await context.request.get(`${BASE}${path}`, { maxRedirects: 0 });
  return { status: r.status(), headers: r.headers(), text: await r.text() };
}

if (MODE === 'api-down') {
  await step('API down -> error state, no data, no mock', async (page) => {
    await page.goto(`${BASE}/`);
    await page.getByText('Cannot load meters').waitFor({ timeout: 20000 });
    assert.equal(await page.locator('[data-testid="meter-table"]').count(), 0);
    assert.equal((await kpi(page, 'kpi-total')).trim(), '—');
    await page.getByText('API unreachable').waitFor();
    await page.screenshot({ path: `${OUT}api-down.png`, fullPage: true });
  });
  await step('API down -> nested route still served (SPA), error shown', async (page) => {
    const resp = await page.goto(`${BASE}/consumer-analytics?device=RTU-1001`);
    assert.equal(resp.status(), 200);
    await page.getByText('Cannot load meters').waitFor({ timeout: 20000 });
  });
} else {
  await step('Overview KPIs follow the approved status rules', async (page) => {
    await page.goto(`${BASE}/`);
    await page.getByRole('button', { name: 'Pump House 1' }).waitFor();
    assert.equal(await kpi(page, 'kpi-total'), '6');
    assert.equal(await kpi(page, 'kpi-active'), '5');
    assert.equal(await kpi(page, 'kpi-online'), '2');   // 5 min, 23 h
    assert.equal(await kpi(page, 'kpi-delayed'), '1');  // 25 h
    assert.equal(await kpi(page, 'kpi-stale'), '1');    // 3 d
    await page.getByTestId('kpi-active').getByText('1 never reported').waitFor();
    await page.waitForFunction(() => /KL/.test(document.querySelector('[data-testid="kpi-total-today"] .ov-kpi-value')?.textContent || ''));
    assert.match(await kpi(page, 'kpi-total-today'), /^[\d,]+\.\d\d\s*KL$/);
    assert.equal(await page.getByTestId('total-today-help').innerText(), 'Sum of consumption of all meters in KL for the last 24 hours');
    assert.equal(await page.locator('[data-testid="meter-table"] tbody tr').count(), 6);
    await page.locator('[data-testid="status-chart"] canvas').waitFor();
    await page.locator('[data-testid="daily-chart"] canvas').waitFor();
    await page.screenshot({ path: `${OUT}overview.png`, fullPage: true });
  });

  await step('Overview detail drawer', async (page) => {
    await page.goto(`${BASE}/`);
    await page.getByRole('button', { name: 'Pump House 1' }).click();
    const drawer = page.locator('[data-testid="meter-drawer"]');
    await drawer.getByText('Latest reading').waitFor();
    await drawer.locator('canvas').waitFor();
    await page.screenshot({ path: `${OUT}overview-drawer.png` });
    await page.keyboard.press('Escape');
    await drawer.waitFor({ state: 'detached' });
  });

  await step('Analytics is device-scoped (no fleet mixing)', async (page) => {
    const tele = [];
    page.on('request', (r) => { if (new URL(r.url()).pathname.startsWith('/api/telemetry')) tele.push(new URL(r.url()).pathname); });
    await page.goto(`${BASE}/analytics`);
    await page.getByTestId('analytics-select-prompt').waitFor();
    await page.waitForTimeout(500);
    assert.equal(tele.length, 0, 'telemetry requested without a meter');
    await page.goto(`${BASE}/analytics?device=RTU-1001`);
    await page.getByTestId('device-analytics').waitFor();
    await page.waitForFunction(() => document.querySelectorAll('.recharts-surface').length >= 4, null, { timeout: 15000 });
    await page.locator('[data-testid="registers-table"]').waitFor();
    assert.ok(tele.length > 0 && tele.every((p) => p === '/api/telemetry/RTU-1001'), tele.join(','));
    assert.equal(await page.locator('.backend-fault-banner').count(), 0);
    await page.screenshot({ path: `${OUT}analytics.png`, fullPage: true });
  });

  await step('GIS: direct load plots only real coordinates; heatmap uses real consumption after Apply', async (page) => {
    const heat = [];
    page.on('request', (r) => { if (r.url().includes('/api/analytics/heatmap')) heat.push(r.url()); });
    const resp = await page.goto(`${BASE}/gis`);
    assert.equal(resp.status(), 200);
    await page.locator('.leaflet-container').waitFor();
    await page.waitForFunction(() => /^3 located · 3 without location$/.test(document.querySelector('[data-testid="gis-counts"]')?.textContent || ''));
    await page.locator('.leaflet-overlay-pane canvas').waitFor();          // markers are drawn on Leaflet's canvas renderer
    await page.getByText(/No location assigned/).click();
    const noLoc = await page.locator('[data-testid="no-location-list"] .no-location-chip').allInnerTexts();
    assert.deepEqual(noLoc.sort(), ['RTU-1003', 'RTU-1004', 'RTU-1006']);
    const box = await page.locator('.gis-map').boundingBox();
    assert.ok(box.height > 400, `map too small: ${box.height}`);
    await page.getByLabel('View mode').selectOption('heatmap');
    await page.getByLabel('Heatmap period').selectOption('7d');
    await page.waitForTimeout(400);
    assert.equal(heat.length, 0, 'heatmap requested before Apply');
    await page.getByRole('button', { name: 'Apply' }).click();
    await page.getByTestId('heat-legend').waitFor();
    assert.match(await page.getByTestId('heat-legend').innerText(), /Highest: [\d,]+\.\d\d KL/);
    assert.ok(heat.some((u) => u.endsWith('period=7d')));
    await page.screenshot({ path: `${OUT}gis.png`, fullPage: true });
  });

  await step('Old /gis-map, /maintenance/*, /settings redirect', async (page) => {
    await page.goto(`${BASE}/gis-map`);
    await page.waitForURL(/\/gis$/);
    await page.goto(`${BASE}/maintenance/RTU-1001`);
    await page.waitForURL(`${BASE}/`);
    await page.goto(`${BASE}/settings`);
    await page.waitForURL(`${BASE}/`);
  });

  await step('Primary navigation is exactly the six pages', async (page) => {
    await page.goto(`${BASE}/`);
    const links = await page.getByRole('navigation', { name: 'Pages' }).getByRole('link').allInnerTexts();
    assert.deepEqual(links.map((t) => t.trim()), ['Overview', 'DMA Analytics', 'NRW Analytics', 'GIS', 'Schematic', 'Consumer Analytics']);
    for (const [label, path] of [['DMA Analytics', '/dma-analytics'], ['NRW Analytics', '/nrw-analytics'], ['GIS', '/gis'], ['Schematic', '/schematic'], ['Consumer Analytics', '/consumer-analytics'], ['Overview', '/']]) {
      await page.getByRole('navigation', { name: 'Pages' }).locator('a', { hasText: label }).click();
      await page.waitForURL(`${BASE}${path}`);
    }
  });

  await step('Schematic: sites and registered meters only', async (page) => {
    await page.goto(`${BASE}/schematic`);
    await page.getByTestId('schematic-canvas').waitFor();
    await page.waitForFunction(() => document.querySelectorAll('.react-flow__node').length === 8);   // 3 sites + 5 meters with a site
    const text = await page.locator('.react-flow').innerText();
    assert.match(text, /Site SITE-NORTH/);
    assert.doesNotMatch(text, /RTU-1006/);                                                          // no site -> not drawn
    await page.screenshot({ path: `${OUT}schematic.png` });
  });

  await step('DMA Analytics and NRW Analytics: compact, no invented data', async (page) => {
    await page.goto(`${BASE}/dma-analytics`);
    await page.getByTestId('dma-not-configured').waitFor();
    assert.equal(await page.locator('canvas').count(), 0);
    await page.screenshot({ path: `${OUT}dma.png` });
    await page.goto(`${BASE}/nrw-analytics`);
    await page.getByTestId('nrw-not-configured').waitFor();
    assert.equal(await page.locator('[data-testid="nrw-kpis"] > div').count(), 6);
    assert.equal(await page.locator('[data-testid="nrw-table"] tbody tr').count(), 3);
    assert.equal(await page.locator('canvas').count(), 0);
    const text = await page.locator('body').innerText();
    assert.doesNotMatch(text, /NaN|Infinity/);
    await page.screenshot({ path: `${OUT}nrw.png` });
  });

  await step('Consumer Analytics: search, real 24h / yesterday / last month, bar chart, trend, history', async (page) => {
    const api = [];
    page.on('request', (r) => { const u = new URL(r.url()); if (u.pathname.startsWith('/api/')) api.push(u.pathname + u.search); });
    await page.goto(`${BASE}/consumer-analytics`);
    assert.equal((await page.getByTestId('consumer-select-prompt').innerText()).trim(), 'Search and select a meter to view historical consumption.');
    assert.equal(await page.locator('canvas').count(), 0);
    const box = page.getByRole('combobox', { name: 'Select meter' });
    await box.fill('Pump');
    await page.getByRole('option', { name: /Pump House 1/ }).click();
    await page.waitForURL(/\/consumer-analytics\?device=RTU-1001$/);
    await page.getByTestId('meter-analytics').waitFor();
    assert.equal(await page.getByTestId('ca-meter-id').innerText(), 'RTU-1001');
    await page.getByTestId('period-last_24h-value').waitFor();
    for (const k of ['last_24h', 'yesterday', 'last_month']) {
      const t = await page.getByTestId(`period-${k}-value`).innerText();
      assert.ok(/KL$/.test(t.trim()) || t.trim() === '—', `${k}: ${t}`);
    }
    assert.match(await page.getByTestId('period-last_24h-value').innerText(), /^[\d,]+\.\d\d KL$/);
    assert.match(await page.getByTestId('period-yesterday-value').innerText(), /^[\d,]+\.\d\d KL$/);
    await page.locator('[data-testid="compare-chart"] canvas').waitFor();
    await page.locator('[data-testid="trend-chart"] canvas').waitFor();
    await page.getByTestId('history-table').waitFor();
    assert.ok(await page.locator('[data-testid="history-table"] tbody tr').count() >= 25);
    await page.getByLabel('Trend window').selectOption('7d');
    await page.getByLabel('Rows per page').selectOption('25');
    await page.getByText('Page 1 / 2').waitFor();
    await page.getByRole('button', { name: 'Next page' }).click();
    await page.getByText('Page 2 /').waitFor();
    assert.ok(api.some((u) => u.startsWith('/api/analytics/devices/RTU-1001/trend?window=7d')));
    assert.ok(!api.some((u) => u.startsWith('/api/telemetry')), 'raw telemetry endpoint used by Consumer Analytics');
    await page.screenshot({ path: `${OUT}consumer.png`, fullPage: true });
  });

  await step('Unknown route -> in-app not found', async (page) => {
    const resp = await page.goto(`${BASE}/no/such/page`);
    assert.equal(resp.status(), 200);
    await page.locator('[data-testid="page-not-found"]').waitFor();
  });

  await step('Testing page: real TCP traffic (valid, unknown, invalid, 58-byte binary)', async (page) => {
    // E2E_TCP_PORT: the fixture's REAL TCP listener (test-only). Sent after the Analytics
    // step so these readings do not change what that step checks.
    if (process.env.E2E_TCP_PORT) {
      const ts = new Date(Date.now() + 330 * 60000).toISOString().slice(0, 19).replace('T', ' ');
      const pk = (id) => JSON.stringify({ deviceId: id, siteid: 'E2E', ts, flow: 3.2, flowUnit: 'm3/h', totalToday: 44 });
      const binary58 = Buffer.concat([Buffer.from([0x16, 0x03, 0x01, 0x00, 0x35]), Buffer.alloc(53, 0x00)]);
      for (const p of [pk('RTU-1001'), pk('STRANGER-42'), 'GET /admin HTTP/1.1\r\n\r\n<script>alert(1)</script>', binary58]) {
        await new Promise((resolve, reject) => {
          const s = net.createConnection(Number(process.env.E2E_TCP_PORT), '127.0.0.1', () => { s.write(p); setTimeout(() => s.end(), 300); });
          s.on('close', resolve); s.on('error', reject);
        });
      }
    }
    const resp = await page.goto(`${BASE}/testing`);
    assert.equal(resp.status(), 200);
    await page.getByRole('heading', { name: 'Testing / Protocol Diagnostics' }).waitFor();
    assert.equal(await page.locator('.storm-topbar, .storm-hero').count(), 0, 'Testing must not render topbar/hero');
    assert.equal(await page.getByRole('navigation', { name: 'Pages' }).count(), 0);
    await page.locator('[data-testid="packet-table"] tbody tr.row').first().waitFor();
    assert.match(await page.getByTestId('server-time').innerText(), /^\d\d-[A-Z][a-z]{2}-\d{4} \d\d:\d\d:\d\d IST$/);
    assert.ok(Number(await page.getByTestId('count-invalid').innerText()) >= 2);
    const statuses = await page.locator('[data-testid="packet-table"] [data-status]').evaluateAll((els) => els.map((e) => e.dataset.status));
    for (const s of ['VALID', 'UNKNOWN_DEVICE', 'INVALID']) assert.ok(statuses.includes(s), statuses.join(','));
    const src = page.getByTestId('sources-table');
    await src.locator('tr[data-key="TCP:STRANGER-42"]').waitFor();
    assert.equal(await src.locator('tr[data-key="TCP:STRANGER-42"] .tst-st').getAttribute('data-status'), 'unknown');
    assert.equal(await src.locator('tr[data-key="TCP:127.0.0.1"] td').first().innerText(), 'UNKNOWN');
    await page.screenshot({ path: `${OUT}testing.png`, fullPage: true });

    await page.locator('[data-testid="packet-table"] tr.row', { hasText: '58 bytes' }).first().click();
    const panel = page.getByTestId('packet-detail');
    await panel.getByText('REJECTED').waitFor();
    assert.equal((await panel.getByTestId('hex-payload').innerText()).trim().split(' ').length, 58);
    assert.ok((await panel.getByTestId('escaped-payload').innerText()).startsWith('\\x16\\x03\\x01\\x005'));
    assert.match(await panel.getByTestId('error-message').innerText(), /No TCP parser could handle packet from 127\.0\.0\.1 \(58 bytes\)/);
    await page.screenshot({ path: `${OUT}testing-detail-binary.png` });
    await page.keyboard.press('Escape');

    await page.locator('[data-testid="packet-table"] tr.row', { hasText: 'STRANGER-42' }).first().click();
    await panel.getByTestId('parsed-telemetry').waitFor();
    assert.match(await panel.getByTestId('parsed-telemetry').innerText(), /STRANGER-42/);
    assert.match(await panel.innerText(), /NOT STORED - device not registered/);
    assert.match(await panel.getByTestId('parsed-telemetry').innerText(), /Battery\s*N\/A/i);
    await page.keyboard.press('Escape');

    await page.locator('[data-testid="packet-table"] tr.row', { hasText: '58 bytes' }).first().waitFor();
    const probe = page.locator('[data-testid="packet-table"] tr.row', { hasText: '48 bytes' }).first();
    await probe.click();
    await panel.getByTestId('raw-payload').waitFor();
    assert.match(await panel.getByTestId('raw-payload').innerText(), /<script>alert\(1\)<\/script>/);   // shown as text
    assert.equal(await panel.locator('script').count(), 0);
    await page.screenshot({ path: `${OUT}testing-detail-text.png` });
    await page.keyboard.press('Escape');
  });

  await step('Former /test-logs URL -> Testing (MQTT), pagination and auto-refresh', async (page) => {
    const calls = [];
    page.on('request', (r) => { if (r.url().includes('/api/diagnostics/packets?')) calls.push(r.url()); });
    await page.goto(`${BASE}/test-logs?tab=mqtt`);
    await page.waitForURL(/\/testing\?protocol=MQTT$/);
    await page.getByText('Page 1 of 3').waitFor();
    assert.equal(await page.locator('[data-testid="packet-table"] tbody tr.row').count(), 50);
    await page.getByRole('button', { name: /NEXT/ }).click();
    await page.getByText('Page 2 of 3').waitFor();
    const n = calls.length;
    await page.waitForTimeout(5600);
    assert.ok(calls.length > n, 'no auto-refresh request within ~5 s');
    assert.ok(calls.every((u) => u.includes('protocol=MQTT') && /page_size=(50|100|250)/.test(u)));
  });

  await step('Production: registered meters only, URL state, dashboard, Open Analytics', async (page) => {
    await page.goto(`${BASE}/production`);
    await page.getByTestId('production-select-prompt').waitFor();
    const box = page.getByRole('combobox', { name: 'Select meter' });
    await box.focus();
    const ids = await page.getByRole('listbox', { name: 'Registered meters' }).getByRole('option').evaluateAll((els) => els.map((e) => e.dataset.device));
    assert.deepEqual(ids.sort(), ['RTU-1001', 'RTU-1002', 'RTU-1003', 'RTU-1004', 'RTU-1005', 'RTU-1006']);   // STRANGER-42 is not a meter
    await box.fill('Pump');
    await page.getByRole('option', { name: /Pump House 1/ }).click();
    await page.waitForURL(/\/production\?device=RTU-1001$/);
    await page.getByTestId('meter-dashboard').waitFor();
    assert.equal(await page.getByTestId('meter-name').innerText(), 'Pump House 1');
    await page.locator('[data-testid="flow-trend"] canvas').waitFor();
    await page.screenshot({ path: `${OUT}production.png`, fullPage: true });
    await page.reload();                                                   // bookmarkable
    await page.getByTestId('meter-dashboard').waitFor();
    await page.getByTestId('open-analytics').click();
    await page.waitForURL(/\/analytics\?device=RTU-1001$/);
    assert.equal(await page.getByTestId('analytics-meter').innerText(), 'Pump House 1');
  });

  await step('Proxy routing and caching headers', async () => {
    const index = await httpGet('/');
    assert.equal(index.status, 200);
    assert.match(index.text, /id="root"/);
    assert.match(index.headers['cache-control'] || '', /no-store/);
    assert.match(index.headers['content-security-policy'] || '', /default-src 'self'/);
    const deep = await httpGet('/consumer-analytics');
    assert.equal(deep.status, 200);
    assert.match(deep.text, /id="root"/);
    const asset = index.text.match(/\/assets\/[^"]+\.js/)[0];
    const a = await httpGet(asset);
    assert.equal(a.status, 200);
    assert.match(a.headers['cache-control'] || '', /immutable/);
    assert.equal((await httpGet('/assets/nope.js')).status, 404);
    const api404 = await httpGet('/api/does-not-exist');
    assert.equal(api404.status, 404);
    assert.equal(JSON.parse(api404.text).detail, 'Not Found');           // FastAPI, not the SPA
    const apiBare = await httpGet('/api');
    assert.equal(apiBare.status, 404);
    assert.doesNotMatch(apiBare.text, /id="root"/);
    const latest = await httpGet('/api/devices/latest');
    assert.equal(latest.status, 200);
    assert.ok(JSON.parse(latest.text).server_time);
    assert.equal(JSON.parse((await httpGet('/health')).text).status, 'ok');
    assert.equal((await httpGet('/nginx-health')).status, 200);
    assert.equal(index.headers['x-frame-options'], 'DENY');
  });

  await step('No requests to other origins (except optional map tiles)', async () => {
    const base = new URL(BASE);
    const foreign = requests.map((r) => new URL(r.url)).filter((u) => u.host !== base.host && !TILE_HOSTS.test(u.hostname));
    assert.deepEqual(foreign.map((u) => u.href), []);
  });
}

await browser.close();
for (const [n, r] of results) console.log(`${r.startsWith('PASS') ? 'PASS' : 'FAIL'}  ${n}${r.startsWith('PASS') ? '' : `  -> ${r.slice(6)}`}`);
if (pageErrors.length) console.log(`PAGE ERRORS:\n  ${pageErrors.join('\n  ')}`);
const failed = results.filter(([, r]) => !r.startsWith('PASS')).length + pageErrors.length;
console.log(`${results.length - results.filter(([, r]) => !r.startsWith('PASS')).length}/${results.length} passed`);
process.exit(failed ? 1 : 0);
