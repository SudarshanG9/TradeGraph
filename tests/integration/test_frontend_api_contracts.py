"""Frontend wire contracts over real authentication, SQL, matching and stores."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from uuid import uuid4

import jwt
import redis
from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.config import Settings
from backend.simulator.agents import TradingAgent, HoldAction
from backend.stores.postgres import query_text
from scripts.verify_schema import db_connect
from tests.integration.test_order_pipeline import accounts, login, order
from tests.integration.test_instrument_catalog import catalog_instruments
from tests.integration.test_polyglot import wait_until


class QuietAgent(TradingAgent):
    def decide(self, *args):
        return HoldAction('Lifecycle contract without financial activity')


def test_login_identity_expiry_and_both_role_boundaries(accounts):
    users, iid = accounts
    with TestClient(create_app()) as client:
        headers = []
        for user, role in ((users[0],'TRADER'),(users[3],'COMPLIANCE_ADMIN')):
            response = client.post('/login',json={k:user[k] for k in ('email','password')})
            assert response.status_code == 200
            body = response.json()
            assert set(body)=={'access_token','token_type','role','expires_in'}
            assert body['role']==role and body['token_type']=='bearer' and body['expires_in']==Settings.from_env().jwt_ttl_seconds
            headers.append({'Authorization':'Bearer '+body['access_token']})
        assert client.post('/login',json={'email':users[0]['email'],'password':'wrong'}).status_code==401
        for h in ({},{'Authorization':'Bearer invalid.jwt.token'}):
            assert client.get('/instruments',headers=h).status_code==401
        s=Settings.from_env(); now=datetime.now(timezone.utc)
        expired=jwt.encode({'sub':str(users[0]['id']),'role':'TRADER','iat':now-timedelta(minutes=5),'exp':now-timedelta(seconds=1)},s.jwt_secret,algorithm=s.jwt_algorithm)
        assert client.get('/instruments',headers={'Authorization':'Bearer '+expired}).status_code==401
        for method,path in (('get','status'),('post','stop'),('post','start')):
            kwargs={'json':{'instrument_ids':[iid]}} if path=='start' else {}
            assert getattr(client,method)('/admin/simulator/'+path,headers=headers[0],**kwargs).status_code==403
        assert client.post('/orders',headers=headers[1],json=order(iid)).status_code==403
        assert client.get('/account/me',headers=headers[1]).status_code==403


def test_simulator_running_stopping_stopped_and_duplicate_start(accounts):
    users,_=accounts
    # Use an existing instrument; the quiet strategy creates no persistent quotes.
    with db_connect() as conn:
        iid=conn.execute('SELECT id FROM instrument WHERE is_active ORDER BY id LIMIT 1').fetchone()[0]
    with TestClient(create_app()) as client:
        admin=login(client,users[3]); s=client.app.state.live_simulator
        s.agent_factory=lambda spec,tid,iid,seed:QuietAgent(tid,iid,seed)
        assert client.get('/admin/simulator/status',headers=admin).json()['state']=='STOPPED'
        assert client.post('/admin/simulator/start',headers=admin,json={'instrument_ids':[iid]}).json()['state']=='RUNNING'
        assert client.post('/admin/simulator/start',headers=admin,json={'instrument_ids':[iid]}).status_code==409
        original=s.coordinator.worker.drain
        async def install_gate():
            import asyncio
            release=asyncio.Event()
            async def gated():
                await release.wait()
                await original()
            s.coordinator.worker.drain=gated
            return release
        release=client.portal.call(install_gate)
        with ThreadPoolExecutor(1) as pool:
            stop=pool.submit(lambda:client.post('/admin/simulator/stop',headers=admin))
            try:
                state=wait_until(lambda:client.get('/admin/simulator/status',headers=admin).json(),lambda r:r['state']=='STOPPING')
                assert not stop.done() and state['orders_attempted']==0
            finally:
                client.portal.call(release.set)
            assert stop.result(timeout=10).json()['state']=='STOPPED'
        s.coordinator.worker.drain=original


def test_http_200_stop_can_mean_error_and_unavailable_worker_is_503(accounts):
    users,iid=accounts
    with TestClient(create_app()) as client:
        admin=login(client,users[3]); s=client.app.state.live_simulator
        s.agent_factory=lambda spec,tid,iid,seed:QuietAgent(tid,iid,seed)
        assert client.post('/admin/simulator/start',headers=admin,json={'instrument_ids':[iid]}).status_code==200
        original=s.coordinator.worker.drain
        async def failed_drain():
            raise RuntimeError('controlled drain failure; no financial orders exist')
        s.coordinator.worker.drain=failed_drain
        try:
            result=client.post('/admin/simulator/stop',headers=admin)
            assert result.status_code==200 and result.json()['state']=='ERROR'
            assert result.json()['last_error']=='STOP_FAILED_RECONCILIATION_REQUIRED'
            assert result.json()['orders_accepted']==result.json()['committed_executions']==0
            assert client.get('/admin/simulator/status',headers=admin).json()['state']=='ERROR'
            assert client.post('/admin/simulator/start',headers=admin,json={'instrument_ids':[iid]}).status_code==409
        finally:
            s.coordinator.worker.drain=original
    with TestClient(create_app(settlement=False)) as client:
        r=client.post('/admin/simulator/start',headers=login(client,users[3]),json={'instrument_ids':[iid]})
        assert r.status_code==503 and r.json()['error']['code']=='TRADING_UNAVAILABLE'


def test_book_empty_uninitialized_ordered_fresh_stale_and_unavailable(accounts,monkeypatch):
    users,iid=accounts
    with db_connect() as conn:
        symbol=conn.execute('SELECT symbol FROM instrument WHERE id=%s',(iid,)).fetchone()[0]
    with TestClient(create_app()) as client:
        a,b=login(client,users[0]),login(client,users[1]); url=f'/market/{symbol}/book'
        store=client.app.state.depth
        wait_until(lambda:client.get(url,headers=a).json(),lambda r:r.get('as_of') is not None)
        store.client.delete(*store.keys(symbol))  # eviction of this fixture's cache only
        missing=client.get(url,headers=a)
        assert missing.status_code==503 and missing.json()['error']['code']=='DEPTH_RESYNC_REQUIRED'
        recovered=wait_until(lambda:client.get(url,headers=a).json(),lambda r:r.get('epoch')==client.app.state.service.epoch)
        assert recovered['bids']==[] and recovered['asks']==[] and recovered['version']==0
        ids=[]
        for h,side,price,qty in ((a,'BUY',100,3),(a,'BUY',99,2),(b,'SELL',103,4),(b,'SELL',102,5)):
            r=client.post('/orders',headers=h,json=order(iid,side,price,qty));assert r.status_code==201
            ids.append((h,r.json()['order_id']))
        book=wait_until(lambda:client.get(url,headers=a).json(),lambda r:r.get('version')==client.app.state.service.version)
        assert book['bids']==[dict(price_ticks=100,quantity=3),dict(price_ticks=99,quantity=2)]
        assert book['asks']==[dict(price_ticks=102,quantity=5),dict(price_ticks=103,quantity=4)]
        assert not book['stale'] and datetime.fromisoformat(book['as_of'].replace('Z','+00:00')).tzinfo
        assert client.get(f'/market/{symbol}/trades',headers=a).json()['items']==[]
        class Later(datetime):
            @classmethod
            def now(cls,tz=None):return datetime.now(tz)+timedelta(seconds=31)
        with monkeypatch.context() as m:
            m.setattr('backend.stores.redis_depth.datetime',Later)
            stale=client.get(url,headers=a).json()
            assert stale['stale'] and stale['version']==book['version'] and stale['bids']==book['bids']
            assert client.get('/health').json()['trading_ready']
        original=store.client
        broken=redis.Redis.from_url('redis://127.0.0.1:1/0',socket_connect_timeout=1,socket_timeout=1)
        try:
            store.client=broken
            r=client.get(url,headers=a)
            assert r.status_code==503 and r.json()['error']['code']=='CACHE_UNAVAILABLE'
        finally:
            store.client=original;broken.close()
        r=client.get('/market/UNKNOWN'+uuid4().hex[:10]+'/book',headers=a)
        assert r.status_code==404 and r.json()['error']['code']=='INSTRUMENT_NOT_FOUND'
        for h,oid in ids:assert client.post(f'/orders/{oid}/cancel',headers=h).status_code==200


def test_only_committed_trades_paginate_and_account_orders_reconcile(accounts):
    users,iid=accounts
    with db_connect() as conn:symbol=conn.execute('SELECT symbol FROM instrument WHERE id=%s',(iid,)).fetchone()[0]
    with TestClient(create_app()) as client:
        a,b=login(client,users[0]),login(client,users[1]); db=client.app.state.database
        assert client.get(f'/market/{symbol}/analytics',headers=a).json()['vwap_ticks'] is None
        entered,release=Event(),Event();original=db.settle
        def gated(event):
            entered.set();assert release.wait(10)
            return original(event)
        db.settle=gated
        try:
            buy=client.post('/orders',headers=a,json=order(iid,quantity=2)).json()['order_id']
            client.post('/orders',headers=b,json=order(iid,'SELL',100,1))
            assert entered.wait(5)
            assert client.get(f'/market/{symbol}/trades',headers=a).json()==dict(items=[],next_before_id=None)
        finally:
            release.set();db.settle=original
        wait_until(lambda:client.get(f'/market/{symbol}/trades',headers=a).json(),lambda r:len(r['items'])==1)
        partial=next(o for o in client.get('/orders/me',headers=a).json()['items'] if o['id']==buy)
        assert (partial['status'],partial['quantity'],partial['filled_quantity'],partial['archived'])==('PARTIAL',2,1,False)
        assert client.post(f'/orders/{buy}/cancel',headers=a).json()['cancelled_quantity']==1
        second=client.post('/orders',headers=a,json=order(iid,price=101)).json()['order_id']
        sell=client.post('/orders',headers=b,json=order(iid,'SELL',101,1)).json()['order_id']
        wait_until(lambda:client.get(f'/market/{symbol}/trades',headers=a).json(),lambda r:len(r['items'])==2)
        page=client.get(f'/market/{symbol}/trades?limit=1',headers=a).json()
        trade=page['items'][0]
        assert page['next_before_id']==trade['id']
        assert type(trade['price_ticks']) is type(trade['quantity']) is int
        assert datetime.fromisoformat(trade['executed_at'].replace('Z','+00:00')).tzinfo
        with db_connect() as conn:
            row=conn.execute('SELECT price_ticks,quantity FROM execution WHERE id=%s',(trade['id'],)).fetchone()
        assert row==(trade['price_ticks'],trade['quantity'])
        older=client.get(f'/market/{symbol}/trades',headers=a,params={'limit':1,'before_id':page['next_before_id']}).json()
        assert older['items'][0]['id']<trade['id']
        assert client.get(f'/market/{symbol}/trades',headers=a,params={'before_id':older['next_before_id']}).json()['items']==[]
        account=client.get('/account/me',headers=a).json()
        assert account['cash_balance']==19797 and account['escrow_balance']==0
        assert account['positions']==[dict(instrument_id=iid,net_quantity=2,realized_pnl=0,pnl_basis='gross')]
        assert client.post(f'/orders/{sell}/cancel',headers=b).json()['error']['code']=='ORDER_TERMINAL'
        with db_connect() as conn:
            conn.execute(query_text('archive'),{'cutoff':datetime.now(timezone.utc)+timedelta(seconds=1),'trader_ids':[users[0]['trader_id']]})
        history=client.get('/orders/me?limit=1',headers=a).json()
        assert history['items'][0]['archived'] and history['next_before_id']==second
        assert client.get('/orders/me',headers=a,params={'before_id':second}).json()['items'][0]['id']==buy


def test_failed_orders_keep_existing_error_contracts(accounts,catalog_instruments):
    users,iid=accounts
    with TestClient(create_app()) as client:
        a=login(client,users[0])
        assert client.post('/orders',json=order(iid)).status_code==401
        cases=[(order(iid,price=0),422,'INVALID_REQUEST'),(order(iid,quantity=0),422,'INVALID_REQUEST'),
               (order(iid,quantity=1000000),409,'INSUFFICIENT_FUNDS'),
               (order(catalog_instruments[0],quantity=1),422,'INVALID_ORDER'),
               (order(catalog_instruments[2]),422,'INVALID_ORDER')]
        for body,status,code in cases:
            r=client.post('/orders',headers=a,json=body)
            assert r.status_code==status and r.json()['error']['code']==code
        h=a|{'Idempotency-Key':'frontend-contract-once'}
        oid=client.post('/orders',headers=h,json=order(iid)).json()['order_id']
        r=client.post('/orders',headers=h,json=order(iid))
        assert r.status_code==201 and r.json()['order_id']==oid
        conflict=client.post('/orders',headers=h,json=order(iid,quantity=2))
        assert conflict.status_code==409 and conflict.json()['error']['code']=='DUPLICATE_REQUEST'
        assert client.post(f'/orders/{oid}/cancel',headers=a).status_code==200
        client.portal.call(client.app.state.service.finish_admissions)
        r=client.post('/orders',headers=a,json=order(iid))
        assert r.status_code==503 and r.json()['error']['code']=='TRADING_UNAVAILABLE'


def test_bigint_account_values_are_preserved_in_current_integer_json_contract(accounts):
    users,_=accounts; value=2**53+123
    with db_connect() as conn:
        conn.execute('UPDATE margin_account SET cash_balance=%s WHERE trader_id=%s',(value,users[0]['trader_id']))
    with TestClient(create_app()) as client:
        r=client.get('/account/me',headers=login(client,users[0]))
        assert r.status_code==200 and r.json()['cash_balance']==value
        assert str(value) in r.text and type(r.json()['cash_balance']) is int
