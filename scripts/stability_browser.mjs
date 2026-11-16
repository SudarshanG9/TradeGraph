/** Actual independent browser sessions for the isolated HTTPS/WSS soak. */
import { createRequire } from 'node:module';
import { readFileSync, writeFileSync } from 'node:fs';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.TRADEGRAPH_PLAYWRIGHT_MODULE ?? 'playwright');
const fixture = JSON.parse(readFileSync(process.env.TRADEGRAPH_BROWSER_FIXTURE, 'utf8'));
const result = { sessions: 0, refreshes: 0, frames: 0, recoverableErrors: 0, fatal: null };
const browser = await chromium.launch({
  executablePath: process.env.TRADEGRAPH_CHROME_EXECUTABLE ?? '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  headless: true,
  args: ['--disable-dev-shm-usage', '--ignore-certificate-errors-spki-list=' + fixture.spki],
});
const contexts = [];
let stopping = false;
for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => { stopping = true; });
const save = () => writeFileSync(fixture.output, JSON.stringify(result, null, 2), { mode: 0o600 });
try {
  for (const user of fixture.users) {
    const context = await browser.newContext(); contexts.push(context);
    const page = await context.newPage();
    page.on('websocket', socket => socket.on('framereceived', () => { result.frames++; }));
    await page.goto(fixture.origin + '/auth');
    await page.locator('[name=email]').fill(user.email);
    await page.locator('[name=password]').fill(user.password);
    await page.locator('button[type=submit]').click();
    await page.waitForURL('**/trader/dashboard', { timeout: 20000 });
    result.sessions++;
  }
  save();
  const end = Date.now() + fixture.duration * 1000;
  let refreshed = Date.now();
  while (!stopping && Date.now() < end) {
    for (let i = 0; i < contexts.length; i++) {
      try {
        const page = contexts[i].pages()[0];
        if (Date.now() - refreshed > 600000) {
          const status = await page.evaluate(async ({origin,user}) => (await fetch(origin + '/api/backend/login', {
            method: 'POST', headers: { 'Content-Type': 'application/json', 'X-TradeGraph-Request': '1' },
            body: JSON.stringify({ email: user.email, password: user.password }),
          })).status, {origin: fixture.origin, user: fixture.users[i]});
          if (status !== 200) throw new Error('Session refresh failed');
        }
        await page.goto(fixture.origin + '/trader/dashboard', { timeout: 15000 });
        await page.locator('main').waitFor({ timeout: 15000 });
        const status = await page.evaluate(async () => (await fetch('/api/backend/account/me')).status);
        if (status !== 200) throw new Error('Authoritative account snapshot failed');
        result.refreshes++;
      } catch { result.recoverableErrors++; }
    }
    if (Date.now() - refreshed > 600000) refreshed = Date.now();
    save();
    for (let i = 0; i < 20 && !stopping; i++) await new Promise(resolve => setTimeout(resolve, 500));
  }
  // Final checks must succeed after all injected interruptions have ended.
  for (const context of contexts) {
    const status = await context.pages()[0].evaluate(async () => (await fetch('/api/backend/account/me')).status);
    if (status !== 200) throw new Error('Browser did not recover');
  }
} catch (error) {
  result.fatal = error.name + ': browser recovery check failed'; process.exitCode = 1;
} finally {
  save(); await browser.close();
}
