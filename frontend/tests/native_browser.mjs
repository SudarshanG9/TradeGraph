/** Real Chrome acceptance against a separately running scoped native fixture. */
import { createRequire } from 'node:module';
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import assert from 'node:assert/strict';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.TRADEGRAPH_PLAYWRIGHT_MODULE ?? 'playwright');
const data = JSON.parse(readFileSync(process.env.TRADEGRAPH_BROWSER_FIXTURE, 'utf8'));
const origin = process.env.TRADEGRAPH_TEST_FRONTEND_ORIGIN ?? 'http://127.0.0.1:3000';
const output = process.env.TRADEGRAPH_BROWSER_RESULTS ?? '/tmp/tradegraph-browser-results';
mkdirSync(output, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath: process.env.TRADEGRAPH_CHROME_EXECUTABLE,
});
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const errors = [];
const report = { pages: [], checks: [] };
page.on('pageerror', (error) => errors.push(error.message));
const wait = async (condition) => {
  for (let i = 0; i < 100; i++) {
    if (await condition()) return;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error('Authoritative browser state did not converge');
};
const json = async (path) => (await page.request.get(origin + path)).json();
const login = async (role) => {
  await page.goto(origin + '/auth');
  await page
    .getByRole('button', { name: role === 'trader' ? 'Trader' : 'Administrator', exact: true })
    .click();
  await page.locator('input[name=email]').fill(data[role].email);
  await page.locator('input[name=password]').fill(data[role].password);
  await page.locator('button[type=submit]').click();
  await page.waitForURL(role === 'trader' ? '**/trader/dashboard' : '**/admin/overview');
};
const terminal = async () => {
  await page.goto(origin + '/trader/terminal');
  await page.getByLabel('Selected instrument').selectOption(String(data.instrument_id));
  await page.getByRole('button', { name: 'Submit BUY Order', exact: true }).waitFor();
  await page.getByLabel('Limit Price (ticks)').fill('100');
  await page.getByLabel('Quantity (units)').fill('1');
};
try {
  await login('trader');
  for (const path of [
    '/trader/dashboard',
    '/trader/account',
    '/trader/analytics',
    '/trader/orders',
    '/trader/terminal',
  ]) {
    const response = await page.goto(origin + path);
    assert.equal(response.status(), 200);
    report.pages.push(path);
  }
  const cookie = (await context.cookies()).find((c) => c.name === 'tradegraph_session');
  assert.ok(cookie?.httpOnly);
  assert.equal(cookie.sameSite, 'Strict');
  const shared = await page.request.get('http://127.0.0.1:3101/api/session');
  assert.equal(shared.status(), 200);
  assert.equal((await shared.json()).role, 'TRADER');
  report.checks.push('shared session across two frontend processes');
  await terminal();
  // Deliver to the real BFF/PostgreSQL, then lose only the browser response.
  await page.route('**/api/backend/orders', async (route) => {
    await route.fetch();
    await route.abort('failed');
  });
  await page.getByRole('button', { name: 'Submit BUY Order', exact: true }).click();
  await page.getByRole('button', { name: 'Check outcome', exact: true }).waitFor();
  assert.equal((await json('/api/backend/orders/me')).items.length, 1);
  await page.unroute('**/api/backend/orders');
  await page.reload();
  await page.getByRole('button', { name: 'Check outcome', exact: true }).click();
  await wait(() => page.getByRole('button', { name: 'Submit BUY Order', exact: true }).isEnabled());
  assert.equal((await json('/api/backend/orders/me')).items.length, 1);
  report.checks.push(
    'real COMMIT response loss, reload and authoritative submission unlock without duplicate',
  );
  await page.screenshot({ path: output + '/submission-reconciled.png' });
  await page.goto(origin + '/trader/orders');
  await page.getByRole('button', { name: 'Cancel', exact: true }).first().click();
  await page.route('**/api/backend/orders/*/cancel', (route) => route.abort('failed'));
  await page.getByRole('button', { name: 'Confirm cancellation', exact: true }).click();
  await page.getByRole('button', { name: 'Check cancellation outcome', exact: true }).waitFor();
  await page.getByRole('button', { name: 'Keep order', exact: true }).click();
  await page.getByRole('button', { name: 'Cancel', exact: true }).first().click();
  await page.getByRole('button', { name: 'Check cancellation outcome', exact: true }).click();
  await page.unroute('**/api/backend/orders/*/cancel');
  await wait(() =>
    page.getByRole('button', { name: 'Confirm cancellation', exact: true }).isEnabled(),
  );
  await page.getByRole('button', { name: 'Confirm cancellation', exact: true }).click();
  await wait(async () => (await json('/api/backend/account/me')).escrow_balance === '0');
  assert.equal((await json('/api/backend/account/me')).cash_balance, '1000000');
  report.checks.push(
    'cancel transport loss, dialog remount, active-state reconciliation and one refund',
  );
  await page.getByRole('button', { name: 'Log out', exact: true }).click();
  await page.waitForURL('**/auth');
  assert.equal(await json('/api/session'), null);
  await login('admin');
  for (const path of [
    '/admin/overview',
    '/admin/desks',
    '/admin/disclosures',
    '/admin/optimizer',
    '/admin/regimes',
    '/admin/surveillance',
  ]) {
    const response = await page.goto(origin + path);
    assert.equal(response.status(), 200);
    report.pages.push(path);
  }
  await page.goto(origin + '/admin/overview');
  await page.getByRole('button', { name: 'Start Simulation', exact: true }).waitFor();
  for (const box of await page.getByRole('checkbox').all()) await box.uncheck();
  await page.getByLabel(data.symbol, { exact: true }).check();
  await page.getByRole('button', { name: 'Start Simulation', exact: true }).click();
  await wait(async () => (await json('/api/backend/admin/simulator/status')).state === 'RUNNING');
  await page.getByRole('button', { name: 'Stop Simulation', exact: true }).click();
  await wait(async () => (await json('/api/backend/admin/simulator/status')).state === 'STOPPED');
  report.checks.push('admin simulator UI start/verified stop');
  await page.screenshot({ path: output + '/admin-verified-stop.png' });
  await page.getByRole('button', { name: 'Log out', exact: true }).click();
  await page.waitForURL('**/auth');
  assert.deepEqual(errors, []);
  report.checks.push('all trader/admin pages, real login/logout, no uncaught browser errors');
  writeFileSync(output + '/browser-acceptance.json', JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
} finally {
  await browser.close();
}
