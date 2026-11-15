"""Real native derived stores; no skipped missing services or synthetic API data."""
import time
from uuid import uuid4
import pytest
import redis
from fastapi.testclient import TestClient
from backend.config import Settings
from backend.api.main import create_app
from backend.stores.redis_depth import RedisDepth
from backend.matching.order_book import OrderBook,Order
from scripts.verify_schema import db_connect
from tests.integration.test_order_pipeline import accounts,login,order


def wait_until(callback,predicate,timeout=5):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        value=callback()
        if predicate(value): return value
        time.sleep(0.01)
    raise AssertionError('Derived store did not converge before deadline')


def test_redis_atomic_price_order_big_quantities_version_and_eviction():
    store=RedisDepth(Settings.from_env().redis_url)
    symbol='TEST'+uuid4().hex[:12]
    try:
        bids=[(100+i,1000-i) for i in range(25)]
        asks=[(200+i,i+1) for i in range(25)]
        assert store.apply(symbol,bids,asks,version=1,epoch='test')
        result=store.read(symbol)
        assert [(r['price_ticks'],r['quantity']) for r in result['bids']]==sorted(bids,reverse=True)[:20]
        assert [r['price_ticks'] for r in result['asks']]==list(range(200,220))
        assert not result['stale']
        assert not store.apply(symbol,[],[],version=0,epoch='test')
        assert store.apply(symbol,[(2**53-1,2**63-1)],[],version=2,epoch='test')
        assert store.read(symbol)['bids']==[{'price_ticks':2**53-1,'quantity':2**63-1}]
        assert store.apply(symbol,[],[],version=3,epoch='test')
        assert store.read(symbol)['bids']==[]
        assert not store.client.exists(*store.keys(symbol)[:4])
        with pytest.raises(ValueError): store.apply(symbol,[(2**53,1)],[],version=4,epoch='test')
    finally:
        store.client.delete(*store.keys(symbol));store.close()


def test_redis_outage_does_not_call_or_corrupt_pure_matcher():
    broken=RedisDepth('redis://127.0.0.1:1/0',timeout=1)
    with pytest.raises(redis.RedisError): broken.read('SYNTHETIC')
    book=OrderBook()
    book.submit(Order(1,'a',1,'BUY',100,2))
    result=book.submit(Order(2,'b',1,'SELL',100,1))
    assert result.fills[0].quantity==1 and book.depth(1,'BUY')==[(100,1)]
    broken.close()


def test_api_depth_25_levels_fill_cancel_and_rebuild(accounts):
    users,instrument=accounts
    with db_connect() as conn: symbol=conn.execute('SELECT symbol FROM instrument WHERE id=%s',(instrument,)).fetchone()[0]
    with TestClient(create_app()) as client:
        a,b=login(client,users[0]),login(client,users[1])
        ids={}
        for price in range(100,125):
            response=client.post('/orders',headers=a,json=order(instrument,price=price))
            assert response.status_code==201,response.text
            ids[price]=response.json()['order_id']
        def snapshot(): return client.get(f'/market/{symbol}/book',headers=a).json()
        result=wait_until(snapshot,lambda r:r.get('version')==client.app.state.service.version)
        assert [r['price_ticks'] for r in result['bids']]==list(range(124,104,-1))
        client.post('/orders',headers=b,json=order(instrument,'SELL',124,1))
        assert client.post(f'/orders/{ids[123]}/cancel',headers=a).status_code==200
        result=wait_until(snapshot,lambda r:r.get('version')==client.app.state.service.version)
        assert [r['price_ticks'] for r in result['bids']]==list(range(122,102,-1))
        settled=wait_until(lambda:client.get(f'/market/{symbol}/trades',headers=a).json(),lambda r:len(r.get('items',[]))==1)
        assert settled['items'][0]['price_ticks']==124
        analytics=client.get(f'/market/{symbol}/analytics',headers=a).json()
        assert analytics['band_volume']==1 and analytics['vwap_ticks']=='124'
        # Canonical pure-book snapshot can rebuild an evicted cache atomically.
        store=client.app.state.depth
        store.client.delete(*store.keys(symbol))
        expected=client.app.state.service.engine.book.depth(instrument,'BUY')[:20]
        store.apply(symbol,expected,[],version=client.app.state.service.version,epoch=client.app.state.service.epoch)
        assert [(r['price_ticks'],r['quantity']) for r in store.read(symbol)['bids']]==expected
        for price,oid in ids.items():
            if price not in (123,124): assert client.post(f'/orders/{oid}/cancel',headers=a).status_code==200


def test_cache_worker_real_connection_failure_and_retry_recovery(accounts):
    users,instrument=accounts
    with db_connect() as conn: symbol=conn.execute('SELECT symbol FROM instrument WHERE id=%s',(instrument,)).fetchone()[0]
    with TestClient(create_app()) as client:
        headers=login(client,users[0])
        store=client.app.state.depth
        original=store.client
        broken=redis.Redis.from_url('redis://127.0.0.1:1/0',decode_responses=True,socket_connect_timeout=1,socket_timeout=1)
        store.client=broken
        try:
            response=client.post('/orders',headers=headers,json=order(instrument))
            assert response.status_code==201
            worker=client.app.state.service.derived['redis']
            wait_until(lambda:worker.failed,lambda r:bool(r))
            assert client.get(f'/market/{symbol}/book',headers=headers).status_code==503
            balance=client.get('/account/me',headers=headers).json()
            assert (balance['cash_balance'],balance['escrow_balance'])==(19899,101)
        finally:
            store.client=original
            broken.close()
        result=wait_until(lambda:client.get(f'/market/{symbol}/book',headers=headers).json(),lambda r:r.get('version')==client.app.state.service.version and bool(r.get('bids')))
        assert result['bids']==[{'price_ticks':100,'quantity':1}]
        assert client.post('/orders/'+str(response.json()['order_id'])+'/cancel',headers=headers).status_code==200
        assert client.get('/account/me',headers=headers).json()['cash_balance']==20000


def test_derived_backlog_overflow_fails_closed():
    from backend.events.dispatcher import Dispatcher,DerivedWorker
    dispatcher=Dispatcher(1)
    worker=DerivedWorker('test',lambda payload:None,dispatcher)
    worker.publish({'version':1})
    with pytest.raises(RuntimeError): worker.publish({'version':2})
    assert dispatcher.failure
    assert worker.queue.qsize()==1
