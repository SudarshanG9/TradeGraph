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
        yield users, instrument
    finally:
        from backend.stores.redis_depth import RedisDepth
        depth=RedisDepth(Settings.from_env().redis_url)
        try: depth.client.delete(*depth.keys(instrument_symbol))
        finally: depth.close()
        with db_connect() as conn:
            conn.execute('DELETE FROM execution WHERE buy_trader_id=ANY(%s) OR sell_trader_id=ANY(%s)',(traders,traders))
            for table in ('position','order_history','order','margin_account','trader'):
                key = 'id' if table=='trader' else 'trader_id'
                conn.execute(f'DELETE FROM public."{table}" WHERE {key}=ANY(%s)',(traders,))
            conn.execute('DELETE FROM user_account WHERE id=ANY(%s)',([u['id'] for u in users],))
            conn.execute('DELETE FROM instrument WHERE id=%s',(instrument,))


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
