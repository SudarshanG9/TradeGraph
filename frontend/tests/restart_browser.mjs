/** Keep a browser authenticated across a clean, explicitly identified test-stack restart. */
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { spawn, execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync, openSync } from 'node:fs';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.TRADEGRAPH_PLAYWRIGHT_MODULE ?? 'playwright');
assert.ok(process.env.POSTGRES_DB?.startsWith('tradegraph_test_'));
const envFile = process.env.TRADEGRAPH_TEST_ENV_FILE;
const pid = Number(process.env.TRADEGRAPH_STACK_PID);
assert.ok(envFile?.startsWith('/tmp/tradegraph-test-') && Number.isInteger(pid) && pid > 1);
const command = execFileSync('ps', ['-p', String(pid), '-o', 'command='], { encoding: 'utf8' });
assert.ok(command.includes('-m scripts.run_local --env-file ' + envFile));
const origin = process.env.APP_ORIGIN;
assert.equal(new URL(origin).hostname, '127.0.0.1');
const output = process.env.TRADEGRAPH_BROWSER_RESULTS ?? '/tmp/tradegraph-restart-browser';
mkdirSync(output, { recursive: true });
const report = { checks: [], errors: [] };
const browser = await chromium.launch({
  headless: true,
  executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
});
let restarted;
const until = async (read, seconds = 45) => {
  for (let i = 0; i < seconds * 4; i++) {
    try {
      if (await read()) return;
    } catch {}
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error('Test stack failed to recover within bounded wait');
};
try {
  const page = await browser.newPage();
  page.on('pageerror', (error) => report.errors.push(error.message));
  await page.goto(origin + '/auth');
  await page.locator('[name=email]').fill('alice@tradegraph.test');
  await page.locator('[name=password]').fill('password123');
  await page.locator('button[type=submit]').click();
  await page.waitForURL('**/trader/dashboard');
  await page.locator('.preview-status').filter({ hasText: 'snapshots verified' }).waitFor();
  const before = await (await page.request.get(origin + '/api/backend/account/me')).json();
  const book = origin + '/api/backend/market/ACME/book';
  const epoch = (await (await page.request.get(book)).json()).epoch;
  process.kill(pid, 'SIGTERM');
  await until(() => {
    try {
      process.kill(pid, 0);
      return false;
    } catch {
      return true;
    }
  });
  await page.locator('.preview-status').filter({ hasText: 'delayed' }).waitFor();
  const stream = openSync(output + '/stack.log', 'a', 0o600);
  restarted = spawn(
    '.venv/bin/python',
    ['-m', 'scripts.run_local', '--env-file', envFile, '--log-dir', output],
    { stdio: ['ignore', stream, stream] },
  );
  await until(async () => (await page.request.get(origin + '/api/session')).status() === 200);
  await page
    .locator('.preview-status')
    .filter({ hasText: 'snapshots verified' })
    .waitFor({ timeout: 45000 });
  assert.equal(new URL(page.url()).pathname, '/trader/dashboard');
  assert.deepEqual(
    await (await page.request.get(origin + '/api/backend/account/me')).json(),
    before,
  );
  const after = await (await page.request.get(book)).json();
  assert.ok(after.epoch && epoch && after.epoch !== epoch);
  assert.deepEqual(after.bids, []);
  assert.deepEqual(after.asks, []);
  report.checks.push(
    'safe full-stack shutdown/restart changes owner epoch, existing browser reconnects and resynchronizes without login or navigation',
    'account snapshot unchanged, empty authoritative book rebuilt, no second owner',
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
  if (restarted && restarted.exitCode === null) {
    restarted.kill('SIGTERM');
    await new Promise((resolve) => restarted.once('exit', resolve));
  }
}
