/** Read-only endpoint recovery against the explicit isolated full-stack fixture. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { mkdirSync, writeFileSync } from 'node:fs';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.TRADEGRAPH_PLAYWRIGHT_MODULE ?? 'playwright');
assert.ok(process.env.POSTGRES_DB?.startsWith('tradegraph_test_'));
const origin = process.env.APP_ORIGIN;
assert.equal(new URL(origin).hostname, '127.0.0.1');
const output = process.env.TRADEGRAPH_BROWSER_RESULTS ?? '/tmp/tradegraph-recovery-browser';
mkdirSync(output, { recursive: true });
const report = { checks: [], errors: [] };
const browser = await chromium.launch({
  headless: true,
  executablePath:
    process.env.TRADEGRAPH_CHROME_EXECUTABLE ??
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
});
try {
  const context = await browser.newContext();
  const page = await context.newPage();
  page.on('pageerror', (e) => report.errors.push(e.message));
  const signin = async (admin) => {
    await page.goto(origin + '/auth');
    if (admin) await page.getByRole('button', { name: 'Administrator', exact: true }).click();
    await page
      .locator('[name=email]')
      .fill(admin ? 'admin@tradegraph.test' : 'alice@tradegraph.test');
    await page.locator('[name=password]').fill('password123');
    await page.locator('button[type=submit]').click();
    await page.waitForURL(admin ? '**/admin/overview' : '**/trader/dashboard');
  };
  await signin(false);
  for (const [routePath, endpoint, recovered] of [
    ['/trader/dashboard', '**/api/backend/account/me', 'Available Cash'],
    ['/trader/dashboard', '**/api/backend/orders/me*', 'Recent Orders'],
    ['/trader/terminal', '**/api/backend/market/*/book', 'Order Book — ACME'],
  ]) {
    await page.route(endpoint, (route) =>
      route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: '{"error":{"code":"INJECTED_DEPENDENCY_FAILURE"}}',
      }),
    );
    await page.goto(origin + routePath);
    await page.getByText('INJECTED DEPENDENCY FAILURE', { exact: false }).waitFor();
    if (endpoint.includes('orders'))
      await page.getByText('Available Cash', { exact: true }).waitFor();
    if (endpoint.includes('account'))
      await page.getByText('Recent Orders', { exact: true }).waitFor();
    if (endpoint.includes('book'))
      await page.getByRole('button', { name: 'Submit BUY Order', exact: true }).waitFor();
    await page.unroute(endpoint);
    await page
      .getByRole('button', { name: 'Retry', exact: true })
      .evaluate((button) => button.click());
    await page.getByText(recovered, { exact: true }).waitFor();
    await page
      .getByText('INJECTED DEPENDENCY FAILURE', { exact: false })
      .waitFor({ state: 'hidden' });
    report.checks.push(endpoint + ': independent 503, unaffected content, Retry recovery');
  }
  await page.goto(origin + '/trader/terminal');
  await page.getByRole('button', { name: 'Submit BUY Order', exact: true }).waitFor();
  const instruments = await page
    .getByLabel('Selected instrument')
    .locator('option')
    .evaluateAll((nodes) => nodes.map((n) => n.value));
  for (let i = 0; i < 15; i++)
    await page.getByLabel('Selected instrument').selectOption(instruments[i % instruments.length]);
  const selected = await page
    .getByLabel('Selected instrument')
    .locator('option:checked')
    .innerText();
  await page.getByText('Order Book — ' + selected, { exact: true }).waitFor();
  report.checks.push('15 rapid instrument changes converge to the selected book');
  await context.clearCookies();
  await signin(true);
  for (const [routePath, endpoint, recovered, submit] of [
    ['/admin/surveillance', '**/api/backend/admin/surveillance/cycles*', 'Cycle candidates', false],
    ['/admin/optimizer', '**/api/backend/admin/optimizer/compare*', 'Execution time', true],
  ]) {
    await page.route(endpoint, (route) =>
      route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: '{"error":{"code":"INJECTED_DEPENDENCY_FAILURE"}}',
      }),
    );
    await page.goto(origin + routePath);
    if (submit) await page.getByRole('button', { name: 'Compare Plans', exact: true }).click();
    await page.getByText('INJECTED DEPENDENCY FAILURE', { exact: false }).waitFor();
    await page.unroute(endpoint);
    await page
      .getByRole('button', { name: 'Retry', exact: true })
      .evaluate((button) => button.click());
    await page.getByText(recovered, { exact: false }).first().waitFor();
    await page
      .getByText('INJECTED DEPENDENCY FAILURE', { exact: false })
      .waitFor({ state: 'hidden' });
    report.checks.push(endpoint + ': injected failure and real backend Retry recovery');
  }
  await context.clearCookies();
  await context.addCookies([
    { name: 'tradegraph_session', value: 'invalid', url: origin, httpOnly: true },
  ]);
  const result = await page.request.get(origin + '/api/session');
  assert.equal(result.status(), 200);
  assert.equal(await result.json(), null);
  await page.goto(origin + '/trader/dashboard');
  await page.waitForURL((url) => url.pathname === '/auth');
  report.checks.push(
    'invalid session returns authoritative null and protected navigation redirects',
  );
  assert.deepEqual(report.errors, []);
  report.status = 'passed';
} catch (error) {
  report.status = 'failed';
  report.failure = error.stack;
  throw error;
} finally {
  writeFileSync(output + '/acceptance.json', JSON.stringify(report, null, 2));
  await browser.close();
}
