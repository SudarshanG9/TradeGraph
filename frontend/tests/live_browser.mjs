/** Real browser UI + same-origin BFF/WS + canonical PostgreSQL acceptance. */
import { createRequire } from 'node:module';
import { randomUUID } from 'node:crypto';
import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import assert from 'node:assert/strict';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.TRADEGRAPH_PLAYWRIGHT_MODULE ?? 'playwright');
const origin = process.env.APP_ORIGIN ?? 'http://127.0.0.1:3000';
const output = process.env.TRADEGRAPH_BROWSER_RESULTS ?? '/tmp/tradegraph-live-browser-results';
assert.ok(process.env.POSTGRES_DB?.startsWith('tradegraph_test_'));
assert.equal(new URL(origin).hostname, '127.0.0.1');
mkdirSync(output, { recursive: true });
const report = { checks: [], pages: [], metrics: {}, errors: [] };
const browser = await chromium.launch({
  headless: true,
  executablePath:
    process.env.TRADEGRAPH_CHROME_EXECUTABLE ??
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  args: ['--disable-dev-shm-usage', '--disk-cache-size=1048576'],
});
const contexts = [];
const replicas = [];
const latencies = [];
let liveFrames = 0;
const observe = (page) => {
  page.on('websocket', (socket) =>
    socket.on('framereceived', (frame) => {
      try {
        const event = JSON.parse(String(frame.payload));
        if (event.schema_version === 1) {
          liveFrames++;
          latencies.push(Date.now() - Date.parse(event.published_at));
        }
      } catch {}
    }),
  );
};
const users = Array.from({ length: 20 }, (_, i) => ({
  email: `browser-live-${randomUUID()}@example.test`,
  password: 'Synthetic-' + randomUUID(),
  full_name: `Browser Trader ${i + 1}`,
}));
const emails = users.map((u) => u.email);
const headers = { Origin: origin, 'X-TradeGraph-Request': '1' };
const fixture = (command) => {
  const result = spawnSync(
    process.env.TRADEGRAPH_PYTHON ?? '.venv/bin/python',
    ['-m', 'frontend.tests.live_fixture', command],
    { input: JSON.stringify(emails), encoding: 'utf8', timeout: 60000 },
  );
  assert.equal(result.status, 0, 'Scoped operator fixture failed: ' + result.stderr.slice(0, 400));
  return JSON.parse(result.stdout);
};
const until = async (read) => {
  for (let i = 0; i < 120; i++) {
    if (await read()) return;
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error('Browser state failed to converge in 12 seconds');
};
const session = async () => {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  contexts.push(context);
  const page = await context.newPage();
  observe(page);
  page.on('pageerror', (e) => report.errors.push(e.message));
  return { context, page };
};
const signin = async (page, user, admin = false) => {
  await page.goto(origin + '/auth');
  if (admin) await page.getByRole('button', { name: 'Administrator', exact: true }).click();
  await page.locator('[name=email]').fill(user.email);
  await page.locator('[name=password]').fill(user.password);
  await page.locator('button[type=submit]').click();
  await page.waitForURL(admin ? '**/admin/overview' : '**/trader/dashboard', { timeout: 15000 });
};
const json = async (page, path) => {
  const r = await page.request.get(origin + path);
  assert.equal(r.status(), 200, `GET ${path}: ${r.status()}`);
  return r.json();
};
try {
  const publicSession = await session();
  const page = publicSession.page;
  for (let i = 0; i < 5; i++) {
    await page.goto(origin + '/auth');
    await page.getByRole('button', { name: 'Sign Up', exact: true }).click();
    for (const [field, value] of Object.entries({
      name: users[i].full_name,
      email: users[i].email,
      password: users[i].password,
      confirm: users[i].password,
    }))
      await page.locator(`[name=${field}]`).fill(value);
    await page.getByRole('button', { name: 'Create trader account', exact: true }).click();
    await page
      .getByText('Account created, awaiting database provisioning.', { exact: false })
      .waitFor();
    assert.equal(
      await page.getByRole('button', { name: 'Create trader account', exact: true }).isDisabled(),
      true,
    );
  }
  for (const user of users.slice(5)) {
    const result = await page.request.post(origin + '/api/backend/register', {
      headers,
      data: user,
    });
    assert.equal(result.status(), 201);
    assert.equal((await result.json()).status, 'PENDING_PROVISIONING');
  }
  const pending = await page.request.post(origin + '/api/backend/login', {
    headers: { ...headers, 'X-TradeGraph-Role': 'TRADER' },
    data: { email: users[0].email, password: users[0].password },
  });
  assert.equal(pending.status(), 403);
  assert.equal((await pending.json()).error.code, 'REGISTRATION_PENDING_PROVISIONING');
  assert.equal(fixture('provision').verified, 20);
  const initial = fixture('snapshot');
  assert.equal(initial.length, 20);
  assert.ok(
    initial.every(
      (u) =>
        u.status === 'ACTIVE' &&
        u.fee_tier === 'STANDARD' &&
        u.cash_balance === '20000' &&
        u.escrow_balance === '0',
    ),
  );
  report.checks.push(
    '5 independent UI signups + 15 BFF registrations, 20 operator-verified ACTIVE RLS identities',
  );
  const active = [];
  for (const user of users.slice(0, 5)) {
    const entry = await session();
    await signin(entry.page, user);
    active.push(entry);
    const account = await json(entry.page, '/api/backend/account/me');
    assert.equal(account.trader_id, initial.find((r) => r.email === user.email).trader_id);
  }
  report.checks.push('5 independent browser logins resolve their new trader identity');
  const [a, b] = active.map((v) => v.page);
  await a
    .locator('.preview-status')
    .filter({ hasText: 'snapshots verified' })
    .waitFor({ timeout: 15000 });
  report.checks.push('real same-origin ticket/upgrade/HTTP snapshot synchronization');
  for (const path of [
    '/trader/dashboard',
    '/trader/account',
    '/trader/orders',
    '/trader/analytics',
    '/trader/terminal',
  ]) {
    assert.equal((await a.goto(origin + path)).status(), 200);
    report.pages.push(path);
  }
  await a.goto(origin + '/trader/dashboard');
  const catalog = await json(a, '/api/backend/instruments');
  const instrument = catalog.items.find((i) => i.symbol === 'ACME') ?? catalog.items[0];
  // Check private HTTP identity and admin access.
  assert.equal((await a.request.get(origin + '/api/backend/admin/desks/rollup')).status(), 403);
  assert.notEqual(
    (await json(a, '/api/backend/account/me')).trader_id,
    (await json(b, '/api/backend/account/me')).trader_id,
  );
  const monitors = [await active[0].context.newPage(), await active[1].context.newPage()];
  for (const monitor of monitors) {
    observe(monitor);
    await monitor.goto(origin + '/trader/dashboard');
    await monitor.getByText('Available Cash', { exact: true }).waitFor();
  }
  // Keep A's dashboard open while B submits via its actual order form.
  await b.goto(origin + '/trader/terminal');
  await b.getByLabel('Selected instrument').selectOption(String(instrument.id));
  await b.getByRole('button', { name: 'SELL', exact: true }).click();
  await b.getByLabel('Limit Price (ticks)').fill('100');
  await b.getByLabel('Quantity (units)').fill('2');
  const sellResponse = b.waitForResponse(
    (r) => r.url().endsWith('/api/backend/orders') && r.request().method() === 'POST',
  );
  await b.getByRole('button', { name: 'Submit SELL Order', exact: true }).click();
  const sell = await sellResponse;
  assert.equal(sell.status(), 201);
  const sellId = (await sell.json()).order_id;
  assert.equal((await a.request.get(origin + '/api/backend/orders/' + sellId)).status(), 404);
  await a.goto(origin + '/trader/terminal');
  await a.getByLabel('Selected instrument').selectOption(String(instrument.id));
  await a.getByLabel('Limit Price (ticks)').fill('100');
  await a.getByLabel('Quantity (units)').fill('2');
  const started = performance.now();
  const buyResponse = a.waitForResponse(
    (r) => r.url().endsWith('/api/backend/orders') && r.request().method() === 'POST',
  );
  await a.getByRole('button', { name: 'Submit BUY Order', exact: true }).click();
  const buy = await buyResponse;
  assert.equal(buy.status(), 201);
  const buyId = (await buy.json()).order_id;
  await until(async () => {
    const sql = fixture('snapshot');
    return sql
      .filter((u) => [users[0].email, users[1].email].includes(u.email))
      .every((u) => u.orders.some((o) => o.status === 'FILLED'));
  });
  await until(
    async () =>
      (await a.getByRole('table', { name: 'Recent Executions' }).count()) > 0 ||
      (await a.locator('body').innerText()).includes('#' + buyId),
  );
  const settled = fixture('snapshot');
  for (const [page, user] of [
    [a, users[0]],
    [b, users[1]],
  ]) {
    const sql = settled.find((u) => u.email === user.email);
    const account = await json(page, '/api/backend/account/me');
    assert.equal(account.cash_balance, sql.cash_balance);
    assert.equal(account.escrow_balance, sql.escrow_balance);
    assert.deepEqual(
      account.positions.map((p) => ({
        instrument_id: p.instrument_id,
        net_quantity: p.net_quantity,
        realized_pnl: p.realized_pnl,
      })),
      sql.positions,
    );
    const orders = await json(page, '/api/backend/orders/me');
    assert.ok(orders.items.some((o) => o.status === 'FILLED'));
    const monitor = monitors[page === a ? 0 : 1];
    await monitor
      .getByRole('table', { name: 'Recent Orders', exact: true })
      .getByText('FILLED', { exact: true })
      .waitFor();
    const metric = monitor.locator('.metric').filter({ hasText: 'Available Cash' });
    await until(async () =>
      (await metric.innerText()).includes(Number(sql.cash_balance).toLocaleString('en-US')),
    );
  }
  report.metrics.first_trade_to_verified_screen_ms = Math.round(performance.now() - started);
  report.checks.push(
    'two real order forms cross, SQL settles once, own balances/positions/orders and screens agree',
  );
  report.checks.push(
    'open dashboard monitors converge automatically without navigation or manual refresh',
  );
  const activityStarted = performance.now();
  const rounds = Number(process.env.TRADEGRAPH_ACTIVITY_ROUNDS ?? 60);
  assert.ok(Number.isInteger(rounds) && rounds >= 10 && rounds <= 120);
  for (let i = 0; i < rounds; i++) {
    const submit = async (page, side) => {
      const response = await page.request.post(origin + '/api/backend/orders', {
        headers: { ...headers, 'Idempotency-Key': randomUUID() },
        data: { instrument_id: instrument.id, side, price_ticks: '100', quantity: '1' },
      });
      assert.equal(response.status(), 201);
      return response.json();
    };
    await submit(b, 'SELL');
    await submit(a, 'BUY');
    if (i % 10 === 3) {
      await active[1].context.setOffline(true);
      await new Promise((r) => setTimeout(r, 500));
      await active[1].context.setOffline(false);
    }
    if (i % 5 === 0) {
      const alternative = catalog.items.find((item) => item.id !== instrument.id);
      if (alternative) {
        await a.getByLabel('Selected instrument').selectOption(String(alternative.id));
        await a.getByLabel('Selected instrument').selectOption(String(instrument.id));
      }
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  await until(async () =>
    fixture('snapshot')
      .filter((u) => [users[0].email, users[1].email].includes(u.email))
      .every((u) => u.orders.length === rounds + 1 && u.orders.every((o) => o.status === 'FILLED')),
  );
  const finalState = fixture('snapshot');
  for (let i = 0; i < 2; i++) {
    const sql = finalState.find((u) => u.email === users[i].email);
    await until(async () =>
      (
        await monitors[i].locator('.metric').filter({ hasText: 'Available Cash' }).innerText()
      ).includes(Number(sql.cash_balance).toLocaleString('en-US')),
    );
    const depth = await json(monitors[i], '/api/backend/market/' + instrument.symbol + '/book');
    assert.deepEqual(depth.bids, []);
    assert.deepEqual(depth.asks, []);
  }
  report.metrics.controlled_activity_ms = Math.round(performance.now() - activityStarted);
  report.metrics.controlled_executions = rounds + 1;
  report.checks.push(
    `${rounds} additional crossing pairs, periodic interrupted receiver and instrument changes, SQL/screen recovery, no resting residuals`,
  );
  for (const monitor of monitors) await monitor.close();
  // Independent widget failure and recovery.
  await a.route('**/api/backend/market/*/trades*', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ error: { code: 'TRADES_TEST_UNAVAILABLE' } }),
    }),
  );
  await a.goto(origin + '/trader/dashboard');
  await a.getByText('TRADES TEST UNAVAILABLE', { exact: false }).waitFor();
  assert.ok(await a.getByText('Available Cash', { exact: true }).isVisible());
  await a.unroute('**/api/backend/market/*/trades*');
  await a.getByRole('button', { name: 'Retry', exact: true }).click();
  await until(
    async () => (await a.getByText('TRADES TEST UNAVAILABLE', { exact: false }).count()) === 0,
  );
  report.checks.push('trades 503 preserves account widget and independent Retry recovers');
  await a.route('**/api/session', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: '{"error":{"code":"SESSION_UNAVAILABLE"}}',
    }),
  );
  await a.goto(origin + '/trader/dashboard');
  await a.getByText('Session service unavailable.', { exact: false }).waitFor();
  assert.equal(new URL(a.url()).pathname, '/trader/dashboard');
  assert.equal(await a.getByText('Available Cash', { exact: true }).count(), 0);
  await a.unroute('**/api/session');
  await a.getByRole('button', { name: 'Retry session', exact: true }).click();
  await a.getByText('Available Cash', { exact: true }).waitFor();
  report.checks.push(
    'session 503 hides protected content without login redirect, retry restores session',
  );
  // Catalogue failure must disable instrument-dependent actions and have a real retry.
  await a.route('**/api/backend/instruments', (route) =>
    route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: '{"error":{"code":"CATALOG_TEST_UNAVAILABLE"}}',
    }),
  );
  await a.goto(origin + '/trader/terminal');
  await a.getByText('CATALOG TEST UNAVAILABLE', { exact: false }).waitFor();
  assert.equal(await a.getByRole('button', { name: 'Submit BUY Order', exact: true }).count(), 0);
  await a.unroute('**/api/backend/instruments');
  await a.getByRole('button', { name: 'Retry catalogue', exact: true }).click();
  await a.getByRole('button', { name: 'Submit BUY Order', exact: true }).waitFor();
  report.checks.push('catalogue 503 disables order form and Retry catalogue restores selection');
  // Explicitly sever a browser socket, then observe ticket renewal/resynchronization.
  const before = await a.request.get(origin + '/api/session');
  assert.equal(before.status(), 200);
  await active[0].context.setOffline(true);
  await new Promise((r) => setTimeout(r, 500));
  await active[0].context.setOffline(false);
  await a
    .locator('.preview-status')
    .filter({ hasText: 'snapshots verified' })
    .waitFor({ timeout: 20000 });
  report.checks.push(
    'browser disconnect/reconnect restores authoritative snapshot synchronization',
  );
  fixture('redis-stop');
  try {
    const unavailable = await a.request.get(origin + '/api/session');
    assert.equal(unavailable.status(), 503);
    assert.equal(unavailable.headers()['set-cookie'], undefined);
    const unavailableLogin = await page.request.post(origin + '/api/backend/login', {
      headers,
      data: { email: users[0].email, password: users[0].password },
    });
    assert.equal(unavailableLogin.status(), 503);
    await a.goto(origin + '/trader/dashboard');
    await a.getByText('Your login could not be verified.', { exact: false }).waitFor();
    assert.equal(new URL(a.url()).pathname, '/trader/dashboard');
    assert.equal(await a.getByText('Available Cash', { exact: true }).count(), 0);
  } finally {
    fixture('redis-start');
  }
  // Redis accepting connections and the BFF reconnecting are separate readiness steps.
  await until(async () => (await a.request.get(origin + '/api/session')).status() === 200);
  await a.getByRole('button', { name: 'Retry', exact: true }).click();
  await a.getByText('Available Cash', { exact: true }).waitFor();
  report.checks.push(
    'actual dedicated Redis stop/restart: login/session 503, no cookie deletion or false redirect, server-layout Retry recovers',
  );
  const replicaEnv = { ...process.env, NODE_ENV: 'production' };
  for (const key of Object.keys(replicaEnv))
    if (
      key.startsWith('POSTGRES_ADMIN') ||
      ['PGPASSWORD', 'POSTGRES_PASSWORD', 'POSTGRES_USER'].includes(key)
    )
      delete replicaEnv[key];
  const startReplica = async () => {
    const child = spawn(
      'node',
      ['node_modules/next/dist/bin/next', 'start', '--hostname', '127.0.0.1', '--port', '3105'],
      { cwd: process.cwd() + '/frontend', env: replicaEnv, stdio: 'ignore' },
    );
    replicas.push(child);
    await until(async () => {
      try {
        return (await a.request.get('http://127.0.0.1:3105/api/session')).status() === 200;
      } catch {
        return false;
      }
    });
    const session = await (await a.request.get('http://127.0.0.1:3105/api/session')).json();
    assert.equal(session.role, 'TRADER');
    return child;
  };
  const first = await startReplica();
  first.kill('SIGTERM');
  await new Promise((r) => first.once('exit', r));
  const second = await startReplica();
  second.kill('SIGTERM');
  await new Promise((r) => second.once('exit', r));
  report.checks.push(
    'same encrypted session works across a second frontend instance and its process restart',
  );
  // Canonical navigation and CSRF (POST must never be replayed).
  const alternate = await page.request.get('http://localhost:' + new URL(origin).port + '/auth', {
    headers: { Accept: 'text/html' },
    maxRedirects: 0,
  });
  assert.equal(alternate.status(), 307);
  const hostile = await a.request.post(origin + '/api/session', {
    headers: { Origin: 'https://evil.test', 'X-TradeGraph-Request': '1' },
  });
  assert.equal(hostile.status(), 403);
  assert.equal(
    (
      await a.request.post(origin + '/api/backend/login', {
        headers: {
          Origin: 'http://localhost:' + new URL(origin).port,
          'X-TradeGraph-Request': '1',
        },
        data: { email: users[0].email, password: users[0].password },
      })
    ).status(),
    403,
  );
  assert.equal((await a.request.post(origin + '/api/session', { headers })).status(), 200);
  assert.equal((await json(b, '/api/session')).role, 'TRADER');
  report.checks.push(
    'foreign/wrong-origin mutations rejected, logout isolated from other browser session',
  );
  const admin = await session();
  await signin(admin.page, { email: 'admin@tradegraph.test', password: 'password123' }, true);
  for (const path of [
    '/admin/overview',
    '/admin/desks',
    '/admin/disclosures',
    '/admin/optimizer',
    '/admin/regimes',
    '/admin/surveillance',
  ]) {
    assert.equal((await admin.page.goto(origin + path)).status(), 200);
    report.pages.push(path);
  }
  await b.screenshot({ path: output + '/settled-trader.png', fullPage: true });
  assert.deepEqual(report.errors, []);
  report.checks.push('all 11 trader/admin pages load without browser exceptions');
  latencies.sort((a, b) => a - b);
  report.metrics.live_frames = liveFrames;
  report.metrics.notification_latency_ms = {
    median: latencies[Math.floor(latencies.length * 0.5)] ?? null,
    p95: latencies[Math.floor(latencies.length * 0.95)] ?? null,
    max: latencies.at(-1) ?? null,
  };
  report.status = 'passed';
} catch (error) {
  report.status = 'failed';
  report.failure = error.stack;
  throw error;
} finally {
  latencies.sort((a, b) => a - b);
  report.metrics.live_frames = liveFrames;
  report.metrics.notification_latency_ms = {
    median: latencies[Math.floor(latencies.length * 0.5)] ?? null,
    p95: latencies[Math.floor(latencies.length * 0.95)] ?? null,
    max: latencies.at(-1) ?? null,
  };
  writeFileSync(output + '/acceptance.json', JSON.stringify(report, null, 2));
  for (const replica of replicas) if (replica.exitCode === null) replica.kill('SIGTERM');
  for (const context of contexts) await context.close();
  await browser.close();
}
