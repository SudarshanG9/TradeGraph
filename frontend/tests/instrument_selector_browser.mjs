/** Exercise the real provider/select during market bursts and slow catalogue reads. */
import { createRequire } from 'node:module';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import http from 'node:http';
import { execFileSync } from 'node:child_process';
import assert from 'node:assert/strict';
const require = createRequire(import.meta.url);
const { build } = require('esbuild');
const { chromium } = require(process.env.TRADEGRAPH_PLAYWRIGHT_MODULE ?? 'playwright');
const directory = mkdtempSync(join(tmpdir(), 'tradegraph-selector-'));
writeFileSync(join(directory, 'navigation.js'), 'export const useRouter = () => ({replace(){}});');
const compiled = await build({
  stdin: {
    contents: `import React from 'react';import {createRoot} from 'react-dom/client';
    import {PreviewProvider,InstrumentSelector,usePreview,useResource} from './src/components/preview-provider';
    function Probe(){const p=usePreview();useResource(async()=>{window.marketReads=(window.marketReads||0)+1;return 1},[],0);
    window.marketEvent=()=>p.refreshResources({type:'book.changed'});window.resync=()=>p.refreshResources({type:'resync.required'});
    window.retryCatalog=p.retryCatalog;return <InstrumentSelector/>;}
    createRoot(document.getElementById('root')).render(<PreviewProvider><Probe/></PreviewProvider>);`,
    resolveDir: resolve('.'),
    loader: 'tsx',
  },
  plugins: process.env.TRADEGRAPH_SELECTOR_BASELINE
    ? [
        {
          name: 'baseline-provider',
          setup(b) {
            b.onLoad({ filter: /preview-provider\.tsx$/ }, () => ({
              contents: execFileSync(
                'git',
                ['show', '2d6a093:frontend/src/components/preview-provider.tsx'],
                { encoding: 'utf8' },
              ),
              loader: 'tsx',
              resolveDir: resolve('src/components'),
            }));
          },
        },
      ]
    : [],
  bundle: true,
  write: false,
  jsx: 'automatic',
  define: { 'process.env.NODE_ENV': '"production"' },
  alias: { 'next/navigation': join(directory, 'navigation.js') },
});
const server = http.createServer((request, response) => {
  response.setHeader(
    'Content-Type',
    request.url === '/bundle.js' ? 'application/javascript' : 'text/html',
  );
  response.end(
    request.url === '/bundle.js'
      ? compiled.outputFiles[0].text
      : '<div id="root"></div><script src="/bundle.js"></script>',
  );
});
await new Promise((r) => server.listen(0, '127.0.0.1', r));
const browser = await chromium.launch({
  headless: true,
  executablePath:
    process.env.TRADEGRAPH_CHROME_EXECUTABLE ??
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
});
try {
  const page = await browser.newPage();
  let reads = 0,
    gate;
  const catalog = {
    items: [1, 2].map((id) => ({
      id,
      symbol: id === 1 ? 'ACME' : 'BETA',
      tick_size: 1,
      lot_size: 1,
      is_active: true,
    })),
  };
  await page.route('**/api/session', (r) =>
    r.fulfill({ json: { kind: 'live', role: 'TRADER', expiresAt: Date.now() + 600000 } }),
  );
  await page.route('**/api/live/ticket', (r) => r.fulfill({ status: 503, json: {} }));
  await page.route('**/api/backend/instruments', async (r) => {
    reads++;
    if (gate) await gate.promise;
    await r.fulfill({ json: catalog });
  });
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  const select = page.getByLabel('Selected instrument');
  await select.locator('option').filter({ hasText: 'BETA' }).waitFor({ state: 'attached' });
  await select.selectOption('2');
  await page.evaluate(() => {
    window.originalSelect = document.querySelector('select');
  });
  const before = reads;
  await page.evaluate(async () => {
    for (let i = 0; i < 30; i++) await window.marketEvent();
  });
  assert.equal(reads, before, 'market events must not reload catalogue');
  assert.equal(await select.inputValue(), '2');
  assert.ok(await page.evaluate(() => window.originalSelect === document.querySelector('select')));
  let release;
  gate = {
    promise: new Promise((r) => {
      release = r;
    }),
  };
  await page.evaluate(() => window.retryCatalog());
  for (let i = 0; reads === before && i < 100; i++) await new Promise((r) => setTimeout(r, 10));
  assert.ok(reads > before);
  assert.equal(await select.isEnabled(), true, 'known select must stay enabled during refresh');
  await select.selectOption('1');
  release();
  gate = undefined;
  await page.evaluate(() => window.resync());
  assert.equal(await select.inputValue(), '1');
  assert.ok(reads > before);
  assert.ok((await page.evaluate(() => window.marketReads)) > 1);
  catalog.items = [];
  await page.evaluate(() => window.resync());
  assert.equal(
    await select.isEnabled(),
    false,
    'empty catalogue must still disable trading selection',
  );
  console.log('PASS: event bursts, delayed catalogue, selection and resync');
} finally {
  await browser.close();
  server.close();
  rmSync(directory, { recursive: true, force: true });
}
