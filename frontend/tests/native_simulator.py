"""BFF simulator proof using the approved isolated backend fixture and one TCP owner.
The ordinary port-8000 API must be stopped before running this module.
"""
import time
from contextlib import asynccontextmanager
from threading import Thread
from uuid import uuid4
import httpx
import uvicorn
from backend.api.main import create_app
from tests.integration.test_live_simulator import live_fixture, proof_factory
from frontend.tests.native_acceptance import ORIGIN, HEADERS


def test_bff_human_bot_settlement_and_safe_stop(live_fixture):
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
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started and time.monotonic() < deadline: time.sleep(.1)
    assert server.started, 'Isolated API did not start; check for a competing owner'
    def wait_for(read, predicate):
        until = time.monotonic() + 12
        while time.monotonic() < until:
            value = read()
            if predicate(value): return value
            time.sleep(.15)
        raise AssertionError('Live simulator observation did not converge')
    orders = []
    with httpx.Client(base_url=ORIGIN, timeout=40) as human, httpx.Client(base_url=ORIGIN, timeout=40) as admin:
        try:
            for client, user, role in [(human, live_fixture['users'][0], 'TRADER'), (admin, live_fixture['users'][1], 'COMPLIANCE_ADMIN')]:
                assert client.post('/api/backend/login', headers=HEADERS | {'X-TradeGraph-Role': role}, json={k: user[k] for k in ('email', 'password')}).status_code == 200
            iid, symbol = live_fixture['iid'], live_fixture['symbol']
            config = {'instrument_ids': [iid], 'bot_count': 8, 'orders_per_second': 5, 'volatility': 'low', 'seed': '20261115', 'max_duration_seconds': 30}
            assert human.post('/api/backend/admin/simulator/start', headers=HEADERS, json=config).status_code == 403
            started = admin.post('/api/backend/admin/simulator/start', headers=HEADERS, json=config)
            assert started.status_code == 200 and started.json()['state'] == 'RUNNING'
            assert admin.post('/api/backend/admin/simulator/start', headers=HEADERS, json=config).status_code == 409
            book = f'/api/backend/market/{symbol}/book'
            trades = f'/api/backend/market/{symbol}/trades'
            wait_for(lambda: human.get(book).json(), lambda x: x.get('asks') == [{'price_ticks': '100', 'quantity': '2'}])
            assert human.get(trades).json()['items'] == []
            for price in ('50', '110'):
                r = human.post('/api/backend/orders', headers=HEADERS | {'Idempotency-Key': str(uuid4())}, json={'instrument_id': iid, 'side': 'BUY', 'price_ticks': price, 'quantity': '1'})
                assert r.status_code == 200
                orders.append(r.json()['order_id'])
            settled = wait_for(lambda: human.get(trades).json()['items'], lambda x: len(x) == 1)
            assert settled[0]['price_ticks'] == '100' and settled[0]['quantity'] == '1'
            status = wait_for(lambda: admin.get('/api/backend/admin/simulator/status').json(), lambda x: x.get('committed_executions') == '1')
            assert int(status['orders_accepted']) >= 1
            stopped = admin.post('/api/backend/admin/simulator/stop', headers=HEADERS, content='null')
            assert stopped.status_code == 200 and stopped.json()['state'] == 'STOPPED'
            assert stopped.json()['active_bot_orders'] == '0'
            own = human.get('/api/backend/orders/me').json()['items']
            assert next(o for o in own if o['id'] == orders[0])['status'] == 'OPEN'
            assert len(human.get(trades).json()['items']) == 1
            wait_for(lambda: human.get(book).json(), lambda x: x.get('asks') == [] and x.get('bids') == [{'price_ticks': '50', 'quantity': '1'}])
        finally:
            admin.post('/api/backend/admin/simulator/stop', headers=HEADERS, content='null')
            for oid in orders: human.post(f'/api/backend/orders/{oid}/cancel', headers=HEADERS, content='null')
            server.should_exit = True
            thread.join(timeout=30)
            assert not thread.is_alive(), 'API must shut down before fixture cleanup'
