"""Measured real WSS clients, reconnect bursts, privacy and settlement isolation."""
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import ssl
import time
from uuid import uuid4

import httpx
import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus
from backend.auth.security import issue_token
from backend.config import Settings
from backend.events.live_bus import LiveBus
from scripts.production_test_stack import ProductionTestStack
from scripts.verify_schema import db_connect
from tests.integration.test_order_pipeline import accounts
from tests.integration.test_production_tls_proxy import signin


def distribution(values):
    values=sorted(values)
    if not values:return {'count':0}
    return {'count':len(values),'p50':values[len(values)//2],
            'p95':values[min(len(values)-1,int(len(values)*.95))],'max':values[-1]}


@contextmanager
def identities(count, users):
    extra=[];traders=[]
    try:
        with db_connect() as conn:
            for _ in range(count-len(users[:3])):
                uid=conn.execute("INSERT INTO user_account(email,password_hash,role) VALUES(%s,'test-only-unused','TRADER') RETURNING id",('capacity-'+uuid4().hex+'@example.test',)).fetchone()[0]
                tid=conn.execute("INSERT INTO trader(user_account_id,full_name) VALUES(%s,'Capacity fixture') RETURNING id",(uid,)).fetchone()[0]
                extra.append({'id':uid,'role':'TRADER','trader_id':tid});traders.append(tid)
        yield users[:3]+extra
    finally:
        with db_connect() as conn:
            conn.execute('DELETE FROM trader WHERE id=ANY(%s)',(traders,))
            conn.execute('DELETE FROM user_account WHERE id=ANY(%s)',([u['id'] for u in extra],))


async def measure(stack, users, iid, count):
    settings=Settings.from_env()
    delivered=[];establish=[];received=[[] for _ in users];connections=[];readers=[]
    semaphore=asyncio.Semaphore(10)
    transport_retries=[]
    async with httpx.AsyncClient(verify=stack.ssl,trust_env=False,timeout=20) as client:
        async def attach(index):
            async with semaphore:
                user=users[index];start=time.perf_counter()
                for attempt in range(3):
                    ws=None
                    try:
                        token=issue_token(user['id'],user['role'],settings)
                        response=await client.post(stack.backend+'/live/ticket',headers={'Authorization':'Bearer '+token},json={'session_key':uuid4().hex*2})
                        assert response.status_code==200
                        ticket=response.json()['ticket']
                        ws=await connect(stack.origin.replace('https:','wss:')+'/live/ws',ssl=stack.ssl,origin=stack.origin,
                            subprotocols=['tradegraph.v1','ticket.'+ticket],max_queue=16,open_timeout=20,proxy=None)
                        assert ws.subprotocol=='tradegraph.v1'
                        await ws.send(json.dumps({'type':'subscribe','instrument_ids':[iid]}))
                        establish.append((time.perf_counter()-start)*1000)
                        return ws
                    except ssl.SSLCertVerificationError:
                        raise  # Never weaken verification or retry an untrusted certificate.
                    except (ssl.SSLError,OSError,TimeoutError) as exc:
                        if ws is not None:await ws.close()
                        transport_retries.append(type(exc).__name__)
                        if attempt==2:raise
                        await asyncio.sleep(.1*(attempt+1))
        async def receive(index,ws):
            try:
                async for raw in ws:
                    message=json.loads(raw)
                    if message['type']=='ping':await ws.send(json.dumps({'type':'pong'}));continue
                    received[index].append(message)
                    delivered.append((datetime.now(timezone.utc)-datetime.fromisoformat(message['published_at'])).total_seconds()*1000)
                    if index==count-1:await asyncio.sleep(.25)
            except Exception:
                pass  # explicit reconnect storm closes all clients
        connections=await asyncio.gather(*(attach(i) for i in range(count)))
        readers=[asyncio.create_task(receive(i,ws)) for i,ws in enumerate(connections)]
        order_latency=[]
        try:
            # Real BFF cookies and financial requests for the two funded traders.
            async with httpx.AsyncClient(verify=stack.ssl,trust_env=False,timeout=20) as a, httpx.AsyncClient(verify=stack.ssl,trust_env=False,timeout=20) as b:
                for c,u in ((a,users[0]),(b,users[1])):
                    r=await c.post(stack.origin+'/api/backend/login',headers={'Origin':stack.origin,'X-TradeGraph-Request':'1'},json={k:u[k] for k in ('email','password')})
                    assert r.status_code==200
                for turn in range(10):
                    buyer,seller=(a,b) if turn%2==0 else (b,a)
                    for c,side in ((buyer,'BUY'),(seller,'SELL')):
                        start=time.perf_counter()
                        r=await c.post(stack.origin+'/api/backend/orders',headers={'Origin':stack.origin,'X-TradeGraph-Request':'1','Idempotency-Key':uuid4().hex},
                            json={'instrument_id':iid,'side':side,'price_ticks':'100','quantity':'1'})
                        assert r.status_code==201,r.text
                        order_latency.append((time.perf_counter()-start)*1000)
            deadline=time.monotonic()+15
            while time.monotonic()<deadline:
                if all(any(m['type']=='trade.committed' for m in messages) for messages in received[:-1]):break
                await asyncio.sleep(.05)
            assert all(any(m['type']=='trade.committed' for m in messages) for messages in received[:-1])
            assert all(not any(m['type'] in ('order.changed','account.changed') for m in messages) for messages in received[2:])
            metrics=(await client.get(stack.backend+'/__test/metrics')).json()
            assert not metrics['financial_failure'] and metrics['max_client_queue']<=128
            # Invalid credentials do not allocate accepted connections.
            for _ in range(10):
                with pytest.raises(InvalidStatus):
                    await connect(stack.origin.replace('https:','wss:')+'/live/ws',ssl=stack.ssl,origin=stack.origin,
                        subprotocols=['tradegraph.v1','ticket.'+'x'*43])
            usage=subprocess.check_output(['ps','-o','pid=,rss=,%cpu=','-p',','.join(str(p.pid) for p in stack.processes.values())],text=True)
        finally:
            await asyncio.gather(*(ws.close() for ws in connections))
            for task in readers:task.cancel()
            await asyncio.gather(*readers,return_exceptions=True)
        # All clients reconnect with fresh single-use credentials at once.
        connections=await asyncio.gather(*(attach(i) for i in range(count)))
        await asyncio.gather(*(ws.close() for ws in connections))
        deadline=time.monotonic()+10
        while time.monotonic()<deadline:
            final=(await client.get(stack.backend+'/__test/metrics')).json()
            if final['clients']==final['socket_tasks']==0:break
            await asyncio.sleep(.1)
        assert final['clients']==final['socket_tasks']==0
        # Settlement must have completed while notification traffic was active.
        assert len(final['settlement_ms'])==10
        return {'clients':count,'connect_ms':distribution(establish),'notification_ms':distribution(delivered),
            'bff_order_ms':distribution(order_latency),'settlement_ms':distribution(final['settlement_ms']),
            'peak_observed_queue':metrics['max_client_queue'],'dropped':final['dropped'],
            'database_connections':metrics['database_connections'],'process_usage':usage.splitlines(),
            'transport_retries':transport_retries,'reconnect_success':count,'accepted_socket_tasks_after_disconnect':final['socket_tasks'],
            'credential_setup':'test-issued signed JWTs; real internal ticket endpoint and full WSS identity validation'}


@pytest.mark.parametrize('count',[10,50,100])
def test_real_wss_capacity(accounts,count):
    binary=os.environ.get('TRADEGRAPH_CADDY')
    if not binary:pytest.skip('Set TRADEGRAPH_CADDY for actual WSS capacity measurement')
    users,iid=accounts
    with identities(count,users) as selected:
        with ProductionTestStack(binary,root=os.environ.get('TRADEGRAPH_TEST_ARTIFACTS')) as stack:
            result=asyncio.run(measure(stack,selected,iid,count))
    target=os.environ.get('TRADEGRAPH_CAPACITY_REPORT')
    if target:
        path=Path(target);data=json.loads(path.read_text()) if path.exists() else {}
        data[str(count)]=result;path.write_text(json.dumps(data,indent=2))


def test_slow_fanout_queue_is_bounded_and_does_not_block_financial_caller():
    # Deterministic overload complements real TCP slow readers (OS buffers vary).
    bus=LiveBus('capacity-test');client=bus.connect({'id':'user','role':'TRADER','trader_id':'trader'})
    client.instruments.add(1)
    for _ in range(10000):bus.publish('book.changed',instrument_id=1,version=1)
    assert client.overflow and client.queue.qsize()==128 and bus.dropped==1
    bus.disconnect(client)
    assert len(bus.clients)==0
