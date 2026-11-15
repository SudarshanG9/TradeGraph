from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient
from backend.api.main import create_app
from scripts.verify_schema import db_connect
from tests.integration.test_order_pipeline import accounts, login


def test_simulator_rbac_validation_and_typed_contract(accounts):
    users, iid = accounts
    with TestClient(create_app()) as client:
        human, admin = login(client, users[0]), login(client, users[3])
        for method, path in (('post','start'), ('post','stop'), ('get','status')):
            fn = getattr(client, method)
            kwargs = {'json': {'instrument_ids': [iid]}} if path == 'start' else {}
            assert fn('/admin/simulator/' + path, **kwargs).status_code == 401
            assert fn('/admin/simulator/' + path, headers=human, **kwargs).status_code == 403
        result = client.get('/admin/simulator/status', headers=admin)
        assert result.status_code == 200 and result.json()['state'] == 'STOPPED'
        for patch in ({'trader_id':str(users[0]['trader_id'])}, {'bot_count':9}, {'bot_count':True},
                      {'orders_per_second':6}, {'volatility':'wild'}, {'max_duration_seconds':0},
                      {'instrument_ids':[iid,iid]}, {'instrument_ids':['1']}, {'instrument_ids':[]}):
            assert client.post('/admin/simulator/start', headers=admin, json={'instrument_ids':[iid]} | patch).status_code == 422
        assert client.post('/admin/simulator/start', headers=admin, json={'instrument_ids':[2**31-1]}).status_code == 422
        assert client.post('/admin/simulator/stop', headers=admin).json()['state'] == 'STOPPED'
        paths = client.get('/openapi.json').json()['paths']
        for path,method in [('start','post'), ('stop','post'), ('status','get')]:
            responses = paths['/admin/simulator/'+path][method]['responses']
            assert '$ref' in responses['200']['content']['application/json']['schema']
            for code in ('401','403'):
                assert responses[code]['content']['application/json']['schema']['$ref'].endswith('/SimulatorError')
        for code in ('409','422','503'):
            assert paths['/admin/simulator/start']['post']['responses'][code]['content']['application/json']['schema']['$ref'].endswith('/SimulatorError')


def test_admin_duplicate_start_shared_owner_and_graceful_shutdown(accounts):
    users, _ = accounts
    # Shared persistent bots use an existing instrument. Preserve their real
    # cancelled order history; never attach it to the disposable accounts fixture.
    with db_connect() as conn:
        iid = conn.execute("SELECT id FROM instrument WHERE is_active AND symbol IN ('RELIANCE','TCS','INFY') ORDER BY id LIMIT 1").fetchone()
        if not iid:
            iid = conn.execute('SELECT id FROM instrument WHERE is_active ORDER BY id LIMIT 1').fetchone()
        iid = iid[0]
    with TestClient(create_app()) as client:
        headers = login(client, users[3])
        assert client.app.state.live_simulator.coordinator is client.app.state.service
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: client.post('/admin/simulator/start', headers=headers,
                json={'instrument_ids':[iid]}), range(2)))
        assert sorted(r.status_code for r in results) == [200,409]
        assert client.get('/admin/simulator/status',headers=headers).json()['state'] == 'RUNNING'
        result = client.post('/admin/simulator/stop',headers=headers)
        assert result.status_code == 200 and result.json()['state'] == 'STOPPED'
        assert result.json()['active_bot_orders'] == 0
        assert not client.app.state.service.closing
        # Let lifespan stop a second session before closing coordinator admissions.
        assert client.post('/admin/simulator/start',headers=headers,json={'instrument_ids':[iid]}).status_code == 200
        owned_task = client.app.state.live_simulator.task
    assert owned_task.done()
    assert client.app.state.live_simulator.state.value == 'STOPPED'


def test_simulator_start_requires_live_settlement_worker(accounts):
    users, iid = accounts
    with TestClient(create_app(settlement=False)) as client:
        result = client.post('/admin/simulator/start',headers=login(client,users[3]),json={'instrument_ids':[iid]})
        assert result.status_code == 503
        assert client.app.state.live_simulator.task is None
