"""Real native PostgreSQL API tests; only uniquely owned synthetic rows are cleaned."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import bcrypt
import jwt
import pytest
from psycopg.errors import InsufficientPrivilege
from fastapi.testclient import TestClient
from backend.api.main import create_app
from backend.config import Settings
from scripts.verify_schema import db_connect


@pytest.fixture
def accounts(request):
    users, traders = [], []
    password = 'synthetic-test-password'
    hashed = bcrypt.hashpw(password.encode(),bcrypt.gensalt()).decode()
    with db_connect() as conn:
        instrument_symbol='T'+uuid4().hex[:16]
        instrument = conn.execute('INSERT INTO instrument(symbol,tick_size,lot_size) VALUES (%s,1,1) RETURNING id',(instrument_symbol,)).fetchone()[0]
        tier = conn.execute('SELECT id FROM fee_tier WHERE tier_name=%s',(getattr(request,'param','STANDARD'),)).fetchone()[0]
        for role in ('TRADER','TRADER','TRADER','COMPLIANCE_ADMIN'):
            email = f'pipeline-{uuid4()}@tradegraph.test'
            uid = conn.execute('INSERT INTO user_account(email,password_hash,role) VALUES (%s,%s,%s) RETURNING id',(email,hashed,role)).fetchone()[0]
            tid = None
            if role=='TRADER':
                tid = conn.execute("INSERT INTO trader(user_account_id,full_name) VALUES (%s,'Synthetic pipeline') RETURNING id",(uid,)).fetchone()[0]
                conn.execute('INSERT INTO margin_account(trader_id,cash_balance,fee_tier_id) VALUES (%s,20000,%s)',(tid,tier))
                traders.append(tid)
            users.append({'id':uid,'email':email,'password':password,'role':role,'trader_id':tid})
    try:
        from scripts.setup_database_identity import provision_test_traders
        provision_test_traders(traders)
        yield users, instrument
    finally:
        from backend.stores.redis_depth import RedisDepth
        from backend.stores.neo4j_graph import Neo4jGraph
        from backend.stores.postgres import Database
        graph=Neo4jGraph(Settings.from_env(),Database(Settings.from_env()))
        try: graph.remove_owned_nodes(traders)
        finally: graph.close()
        depth=RedisDepth(Settings.from_env().redis_url)
        try: depth.client.delete(*depth.keys(instrument_symbol))
        finally: depth.close()
        with db_connect() as conn:
            conn.execute('DELETE FROM regime_snapshot WHERE instrument_id=%s',(instrument,))
            conn.execute('DELETE FROM market_disclosure WHERE instrument_id=%s',(instrument,))
            conn.execute('DELETE FROM order_request_identity WHERE trader_id=ANY(%s)',(traders,))
            conn.execute('DELETE FROM execution WHERE buy_trader_id=ANY(%s) OR sell_trader_id=ANY(%s)',(traders,traders))
            for table in ('position','order_history','order','margin_account','trader'):
                key = 'id' if table=='trader' else 'trader_id'
                conn.execute(f'DELETE FROM public."{table}" WHERE {key}=ANY(%s)',(traders,))
            conn.execute('DELETE FROM user_account WHERE id=ANY(%s)',([u['id'] for u in users],))
            conn.execute('DELETE FROM instrument WHERE id=%s',(instrument,))
        provision_test_traders(traders,remove=True)


def login(client, user):
    response = client.post('/login',json={k:user[k] for k in ('email','password')})
    assert response.status_code == 200, response.text
    assert 'password' not in response.text
    return {'Authorization':'Bearer '+response.json()['access_token']}


def order(instrument, side='BUY', price=100, quantity=1):
    return {'instrument_id':instrument,'side':side,'price_ticks':price,'quantity':quantity}


def test_api_identity_commit_boundary_events_and_concurrent_admission(accounts):
    users, instrument = accounts
    with TestClient(create_app(settlement=False)) as client:
        a,b = login(client,users[0]), login(client,users[1])
        assert client.get('/health').json()['dependencies']=={'postgres':'up','redis':'up','neo4j':'up'}
        assert client.post('/orders',json=order(instrument)).status_code==401
        assert client.post('/orders',headers=login(client,users[3]),json=order(instrument)).status_code==403
        assert client.post('/orders',headers=a,json=order(instrument)|{'trader_id':str(users[1]['trader_id'])}).status_code==422
        assert client.post('/orders',headers=a,json=order(instrument,price=1.5)).status_code==422
        service=client.app.state.service
        admitted=[]
        original=service.engine.submit
        def verified_submit(incoming):
            with db_connect() as conn:
                assert conn.execute('SELECT id FROM public."order" WHERE id=%s',(incoming.order_id,)).fetchone()
            admitted.append(incoming.order_id)
            return original(incoming)
        service.engine.submit=verified_submit
        with ThreadPoolExecutor(4) as pool:
            results=list(pool.map(lambda _:client.post('/orders',headers=a,json=order(instrument)),range(8)))
        assert all(r.status_code==201 for r in results)
        assert admitted==sorted(admitted)
        rejected=client.post('/orders',headers=a,json=order(instrument,quantity=100000))
        assert rejected.status_code==409
        assert len(admitted)==8
        cross=client.post('/orders',headers=b,json=order(instrument,'SELL',99,3))
        assert cross.status_code==201
        assert service.dispatcher.queue.qsize()==3
        events=list(service.dispatcher.queue._queue)
        assert all(e.taker_order_id==cross.json()['order_id'] and e.price_ticks==100 for e in events)
        with db_connect() as conn:
            assert conn.execute('SELECT count(*) FROM execution WHERE sell_trader_id=%s',(users[1]['trader_id'],)).fetchone()[0]==0
        assert client.get('/account/me',headers=a).json()['escrow_balance']>0
        assert len(client.get('/orders/me',headers=a).json()['items'])==8


def test_jwt_expiry_role_spoof_and_runtime_privileges(accounts):
    users,_=accounts
    settings=Settings.from_env()
    with TestClient(create_app(settings,settlement=False)) as client:
        assert client.post('/login',json={'email':users[0]['email'],'password':'wrong'}).status_code==401
        now=datetime.now(timezone.utc)
        for role,expiry in [('TRADER',now-timedelta(seconds=1)),('COMPLIANCE_ADMIN',now+timedelta(minutes=1))]:
            token=jwt.encode({'sub':str(users[0]['id']),'role':role,'iat':now-timedelta(minutes=2),'exp':expiry},settings.jwt_secret,algorithm='HS256')
            assert client.get('/account/me',headers={'Authorization':'Bearer '+token}).status_code==401
        db=client.app.state.database
        with db.connect() as conn:
            row=conn.execute("SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=current_user").fetchone()
            assert not any(row.values())
            with pytest.raises(InsufficientPrivilege): conn.execute('UPDATE margin_account SET cash_balance=0')
        with db.connect() as conn:
            conn.execute('SET LOCAL ROLE trader_role')
            conn.execute("SET LOCAL app.role='COMPLIANCE_ADMIN'")
            with pytest.raises(InsufficientPrivilege): conn.execute('SELECT * FROM market_disclosure')


def test_startup_refuses_second_owner_and_unresolved_orders(accounts):
    users,instrument=accounts
    with TestClient(create_app(settlement=False)) as client:
        with pytest.raises(RuntimeError,match='Another matching owner'):
            with TestClient(create_app(settlement=False)): pass
        assert client.post('/orders',headers=login(client,users[0]),json=order(instrument)).status_code==201
    with pytest.raises(RuntimeError,match='operator reconciliation'):
        with TestClient(create_app(settlement=False)): pass


def test_queue_backpressure_precedes_reservation(accounts):
    from dataclasses import replace
    users,instrument=accounts
    settings=replace(Settings.from_env(),event_queue_capacity=1)
    with TestClient(create_app(settings,settlement=False)) as client:
        a,b=login(client,users[0]),login(client,users[1])
        assert client.post('/orders',headers=a,json=order(instrument)).status_code==201
        assert client.post('/orders',headers=a,json=order(instrument)).status_code==201
        assert client.post('/orders',headers=b,json=order(instrument,'SELL',100,2)).status_code==503
        with db_connect() as conn:
            assert conn.execute('SELECT count(*) FROM public."order" WHERE trader_id=%s',(users[1]['trader_id'],)).fetchone()[0]==0
            assert conn.execute('SELECT cash_balance,escrow_balance FROM margin_account WHERE trader_id=%s',(users[1]['trader_id'],)).fetchone()==(20000,0)


def test_full_api_commit_settlement_partial_cancel_and_stp(accounts):
    users,instrument=accounts
    with TestClient(create_app()) as client:
        a,b=login(client,users[0]),login(client,users[1])
        buy=client.post('/orders',headers=a,json=order(instrument,quantity=100)).json()['order_id']
        sell=client.post('/orders',headers=b,json=order(instrument,'SELL',100,50)).json()['order_id']
        # Cancellation drains every earlier financial event before releasing R(q).
        response=client.post(f'/orders/{buy}/cancel',headers=a)
        assert response.status_code==200 and response.json()['cancelled_quantity']==50
        assert client.get('/account/me',headers=a).json()['cash_balance']==14999
        assert client.get('/account/me',headers=b).json()['cash_balance']==24999
        assert client.post(f'/orders/{sell}/cancel',headers=b).status_code==409
        assert client.post(f'/orders/{buy}/cancel',headers=b).status_code==404
        assert client.post(f'/orders/{buy}/cancel',headers=a).json()['cancelled_quantity']==0
        # Self-trade protection cancels only the incoming residual and refunds it.
        resting=client.post('/orders',headers=a,json=order(instrument,'SELL',100,2)).json()['order_id']
        incoming=client.post('/orders',headers=a,json=order(instrument,'BUY',100,2)).json()['order_id']
        own=client.get('/orders/me',headers=a).json()['items']
        assert next(r for r in own if r['id']==incoming)['status']=='CANCELLED'
        assert next(r for r in own if r['id']==resting)['status']=='OPEN'
        assert client.post(f'/orders/{resting}/cancel',headers=a).status_code==200
        assert client.get('/health').json()['trading_ready']


def test_financial_worker_failure_retains_event_and_fails_closed(accounts):
    users,instrument=accounts
    with TestClient(create_app()) as client:
        a,b=login(client,users[0]),login(client,users[1])
        client.post('/orders',headers=a,json=order(instrument))
        def fail(event): raise RuntimeError('injected settlement failure')
        client.app.state.database.settle=fail
        client.post('/orders',headers=b,json=order(instrument,'SELL'))
        assert not client.get('/health').json()['trading_ready']
        service=client.app.state.service
        assert service.worker.pending is not None
        assert service.dispatcher.failure
        assert client.post('/orders',headers=a,json=order(instrument)).status_code==503
        assert client.post(f'/orders/{service.worker.pending.buy_order_id}/cancel',headers=a).status_code==503
        with db_connect() as conn:
            assert conn.execute('SELECT count(*) FROM execution WHERE buy_trader_id=%s',(users[0]['trader_id'],)).fetchone()[0]==0


def test_admin_query_role_gates_and_actual_plan(accounts):
    users,instrument=accounts
    with TestClient(create_app()) as client:
        trader_headers=login(client,users[0]); admin_headers=login(client,users[3])
        for path in ('/admin/desks/rollup','/admin/optimizer/compare'):
            assert client.get(path,headers=trader_headers).status_code==403
            result=client.get(path,headers=admin_headers)
            assert result.status_code==200, result.text
        plan=client.get('/admin/optimizer/compare',headers=admin_headers).json()
        assert 'Actual Rows' in plan['plans']['automatic']['Plan']
        assert client.get('/admin/optimizer/compare?scenario=SELECT%201',headers=admin_headers).status_code==422


def test_request_key_replay_is_durable_and_precedes_reservation(accounts):
    users,instrument=accounts
    with TestClient(create_app()) as client:
        headers=login(client,users[0])|{'Idempotency-Key':'same-request'}
        first=client.post('/orders',headers=headers,json=order(instrument))
        assert first.status_code==201
        repeated=client.post('/orders',headers=headers,json=order(instrument))
        assert repeated.status_code==201 and repeated.json()==first.json()
        conflict=client.post('/orders',headers=headers,json=order(instrument,quantity=2))
        assert conflict.status_code==409 and conflict.json()['error']['code']=='DUPLICATE_REQUEST'
        other=client.post('/orders',headers=login(client,users[1])|{'Idempotency-Key':'same-request'},json=order(instrument))
        assert other.status_code==201 and other.json()['order_id']!=first.json()['order_id']
        assert client.post('/orders/'+str(other.json()['order_id'])+'/cancel',headers=login(client,users[1])).status_code==200
        assert len(client.get('/orders/me',headers=headers).json()['items'])==1
        assert client.post('/orders/'+str(first.json()['order_id'])+'/cancel',headers=headers).status_code==200


def test_complete_native_simulation_and_existing_data_preservation():
    from backend.simulator.market_simulator import run
    report=run(20261115)
    assert report['executions']==18
    assert report['race_accepted']==3 and report['race_rejected']==5
    assert report['existing_data_preserved']
    assert report['clean_restart_analytics']=='rehydrated from committed executions'
    assert report['scoped_cleanup']=='complete'


def test_openapi_declares_all_frozen_response_models(accounts):
    users,_=accounts
    with TestClient(create_app()) as client:
        schema=client.get('/openapi.json').json()
        paths=schema['paths']
        expected=['/login','/health','/orders','/orders/{order_id}/cancel','/orders/me','/account/me',
                  '/market/{symbol}/book','/market/{symbol}/trades','/market/{symbol}/analytics',
                  '/admin/surveillance/cycles','/admin/regimes/similar','/admin/disclosures/search','/admin/optimizer/compare','/admin/desks/rollup']
        for path in expected:
            method='post' if path in ('/login','/orders','/orders/{order_id}/cancel') else 'get'
            code='201' if path=='/orders' else '200'
            assert '$ref' in paths[path][method]['responses'][code]['content']['application/json']['schema']
        result=client.get('/admin/optimizer/compare',headers=login(client,users[3])).json()
        assert result['row_count']==result['plans']['automatic']['Plan']['Actual Rows']


def test_canceled_reservation_holds_owner_until_commit_thread_finishes(accounts):
    from threading import Event
    from backend.stores.postgres import Database
    from backend.risk.order_reservation import Coordinator
    from backend.api.routes.orders import NewOrder
    users,instrument=accounts
    committed,release=Event(),Event()
    settings=Settings.from_env();db=Database(settings)
    original=db.reserve
    def delayed_ack(*args):
        result=original(*args)  # actual native COMMIT, not mocked financial success
        committed.set()
        assert release.wait(15)
        return result
    db.reserve=delayed_ack
    async def exercise():
        coordinator=Coordinator(db,settings)
        task=asyncio.create_task(coordinator.admit(users[0]['trader_id'],NewOrder(**order(instrument))))
        try:
            assert await asyncio.to_thread(committed.wait,5)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            with pytest.raises(RuntimeError,match='Another matching owner'): db.acquire_owner()
            release.set()
            with pytest.raises(asyncio.CancelledError): await task
            assert coordinator.dispatcher.failure
            with pytest.raises(RuntimeError):
                await coordinator.admit(users[0]['trader_id'],NewOrder(**order(instrument)))
            with db_connect() as conn:
                assert conn.execute('SELECT cash_balance,escrow_balance FROM margin_account WHERE trader_id=%s',(users[0]['trader_id'],)).fetchone()==(19899,101)
                assert conn.execute('SELECT count(*) FROM public."order" WHERE trader_id=%s AND status=\'OPEN\'',(users[0]['trader_id'],)).fetchone()[0]==1
        finally:
            release.set()
            if not task.done():
                task.cancel()
                try: await task
                except asyncio.CancelledError: pass
            await coordinator.finish_admissions()
            coordinator.close()
        with pytest.raises(RuntimeError,match='operator reconciliation'): db.acquire_owner()
    asyncio.run(exercise())


def test_noncrossing_orders_above_queue_capacity_reserve_once(accounts):
    from dataclasses import replace
    users, instrument = accounts
    settings = replace(Settings.from_env(), event_queue_capacity=1)
    with TestClient(create_app(settings, settlement=False)) as client:
        headers = login(client, users[0])
        service = client.app.state.service
        reserved = []
        original = service.database.reserve
        def track(*args):
            row = original(*args)
            reserved.append(row['id'])
            return row
        service.database.reserve = track
        for _ in range(4):
            assert client.post('/orders', headers=headers, json=order(instrument)).status_code == 201
        assert len(reserved) == len(set(reserved)) == 4
        assert service.dispatcher.queue.qsize() == 0
        assert len(service.engine.book._by_id) > service.dispatcher.queue.maxsize
        with db_connect() as conn:
            assert conn.execute('SELECT cash_balance,escrow_balance FROM margin_account WHERE trader_id=%s',
                                (users[0]['trader_id'],)).fetchone() == (19596, 404)


def test_request_outcome_is_owned_readonly_and_survives_lost_response(accounts):
    users, instrument = accounts
    with TestClient(create_app()) as client:
        a, b = login(client,users[0]), login(client,users[1])
        service = client.app.state.service
        original = service.database.reserve
        def lost_ack(*args):
            original(*args)
            import psycopg
            raise psycopg.OperationalError('injected acknowledgement loss')
        service.database.reserve = lost_ack
        assert client.post('/orders',headers=a|{'Idempotency-Key':'lost-ack'},json=order(instrument)).status_code==503
        outcome=client.get('/orders/requests/lost-ack',headers=a)
        assert outcome.status_code==200 and outcome.json()['status']=='ACCEPTED'
        assert client.get('/orders/requests/lost-ack',headers=b).json()['status']=='UNRESOLVED'
        assert client.get('/orders/requests/lost-ack').status_code==401
        service.database.reserve = original
        replay=client.post('/orders',headers=a|{'Idempotency-Key':'lost-ack'},json=order(instrument))
        assert replay.status_code==201 and replay.json()==outcome.json()['accepted_order']
        assert service.dispatcher.failure
        with db_connect() as conn:
            assert conn.execute('SELECT count(*) FROM public."order" WHERE trader_id=%s',(users[0]['trader_id'],)).fetchone()==(1,)
            assert conn.execute('SELECT cash_balance,escrow_balance FROM margin_account WHERE trader_id=%s',(users[0]['trader_id'],)).fetchone()==(19899,101)


def test_owned_cancellation_status_and_repeat_refund(accounts):
    users, instrument=accounts
    with TestClient(create_app()) as client:
        a,b=login(client,users[0]),login(client,users[1])
        oid=client.post('/orders',headers=a,json=order(instrument)).json()['order_id']
        assert client.get(f'/orders/{oid}',headers=b).status_code==404
        assert client.get(f'/orders/{oid}',headers=a).json()['status']=='OPEN'
        assert client.post(f'/orders/{oid}/cancel',headers=a).json()['cancelled_quantity']==1
        assert client.get(f'/orders/{oid}',headers=a).json()['status']=='CANCELLED'
        before=client.get('/account/me',headers=a).json()
        assert client.post(f'/orders/{oid}/cancel',headers=a).json()['cancelled_quantity']==0
        assert client.get('/account/me',headers=a).json()==before
        assert before['cash_balance']==20000 and before['escrow_balance']==0


def test_readiness_distinguishes_owner_replay_worker_and_reconciliation(accounts):
    with TestClient(create_app()) as client:
        result=client.get('/health').json()
        assert result['trading_ready']
        assert result['readiness']['matching_owner'] and result['readiness']['replay_complete']
        assert result['readiness']['financial_settlement']
        client.app.state.service.dispatcher.failure='operator reconciliation required'
        failed=client.get('/health').json()
        assert not failed['trading_ready'] and failed['readiness']['reconciliation_required']
    with TestClient(create_app(settlement=False)) as client:
        result=client.get('/health').json()
        assert not result['trading_ready'] and not result['readiness']['financial_settlement']


def test_terminal_cancel_reconciles_after_real_commit_ack_loss_without_reset(accounts):
    import psycopg
    users,instrument=accounts
    with TestClient(create_app()) as client:
        headers=login(client,users[0])
        oid=client.post('/orders',headers=headers,json=order(instrument)).json()['order_id']
        service=client.app.state.service;original=service.database.cancel
        def lost(*args): original(*args);raise psycopg.OperationalError('lost cancellation acknowledgement')
        service.database.cancel=lost
        assert client.post(f'/orders/{oid}/cancel',headers=headers).status_code==503
        result=client.get(f'/orders/{oid}',headers=headers)
        assert result.status_code==200 and result.json()['status']=='CANCELLED'
        assert service.dispatcher.failure
        assert client.get('/account/me',headers=headers).json()['cash_balance']==20000
        service.database.cancel=original
