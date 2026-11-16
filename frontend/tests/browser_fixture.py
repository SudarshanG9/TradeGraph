"""Scoped browser-acceptance owner. No other FastAPI owner may be running.
Uses the existing approved live fixture and deterministic quote seam. Secrets are
written only to ignored test-results and removed after safe shutdown/cleanup.
Create test-results/finish-browser to request cleanup.
"""
import json
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from threading import Thread
import httpx
import pytest
import uvicorn
from backend.api.main import create_app
from tests.integration.test_live_simulator import live_fixture, proof_factory

root = Path(__file__).resolve().parents[1] / 'test-results'
root.mkdir(exist_ok=True)
finish = root / 'finish-browser'
finish.unlink(missing_ok=True)
metadata = root / 'browser-fixture.json'
patch = pytest.MonkeyPatch()
fixture = live_fixture.__wrapped__(patch)
data = next(fixture)
app = create_app()
lifespan = app.router.lifespan_context
@asynccontextmanager
async def isolated(application):
    async with lifespan(application):
        application.state.live_simulator.agent_factory = proof_factory
        yield
app.router.lifespan_context = isolated
server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=8000, workers=1, log_level='error', access_log=False))
thread = Thread(target=server.run, daemon=True)
try:
    thread.start()
    until = time.monotonic() + 20
    while not server.started and time.monotonic() < until: time.sleep(.1)
    if not server.started: raise RuntimeError('Isolated API startup failed')
    metadata.write_text(json.dumps({'symbol': data['symbol'], 'instrument_id': data['iid'], 'trader': {k: data['users'][0][k] for k in ('email','password')}, 'admin': {k: data['users'][1][k] for k in ('email','password')}}))
    metadata.chmod(0o600)
    print('Isolated browser fixture ready; credentials are in ignored test-results.', flush=True)
    until = time.monotonic() + 1800
    while not finish.exists() and time.monotonic() < until: time.sleep(.2)
finally:
    if server.started:
        with httpx.Client(base_url='http://127.0.0.1:8000', timeout=40) as client:
            for index in (1, 0):
                user = data['users'][index]
                login = client.post('/login', json={k: user[k] for k in ('email','password')})
                login.raise_for_status()
                headers = {'Authorization': 'Bearer ' + login.json()['access_token']}
                if index == 1:
                    stopped = client.post('/admin/simulator/stop', headers=headers)
                    if stopped.json()['state'] != 'STOPPED': raise RuntimeError('Simulator cleanup requires reconciliation')
                else:
                    rows = client.get('/orders/me', headers=headers, params={'limit':100}).json()['items']
                    for row in rows:
                        if row['status'] in ('OPEN','PARTIAL'):
                            client.post(f"/orders/{row['id']}/cancel", headers=headers).raise_for_status()
    server.should_exit = True
    thread.join(timeout=30)
    if thread.is_alive(): raise RuntimeError('Owner did not shut down; cleanup refused')
    metadata.unlink(missing_ok=True)
    finish.unlink(missing_ok=True)
    try: next(fixture)
    except StopIteration: pass
    patch.undo()
    print('Browser fixture safely stopped and cleaned.', flush=True)
