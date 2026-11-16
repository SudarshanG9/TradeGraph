"""Measured HTTPS/WSS soak against NEW isolated fixtures; never an active database.

Requires scripts.with_test_environment and a real Caddy binary. Reports raw measured
samples and explicitly distinguishes scoped fault injection from service shutdown.
"""
import argparse
import asyncio
from collections import deque
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import statistics
import subprocess
import time
from types import SimpleNamespace
from uuid import uuid4

import httpx
import redis
from websockets.asyncio.client import connect
from backend.config import Settings, ROOT
from backend.stores.postgres import Database
from scripts.production_test_stack import ProductionTestStack
from scripts.reconcile_restart import diagnose
from tests.integration.test_order_pipeline import accounts


def distribution(values):
    values=sorted(values)
    if not values:return {'count':0}
    return {'count':len(values),'p50':values[len(values)//2],
            'p95':values[min(len(values)-1,int(len(values)*.95))],'max':values[-1]}


def private_json(path,value):
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(descriptor,'w') as stream:json.dump(value,stream)


async def run(stack, users, iid, duration, output, *, interruptions):
    settings=Settings.from_env();db=Database(settings)
    report={'started_at':datetime.now(timezone.utc).isoformat(),'requested_seconds':duration,
            'traders':len(users[:3]),'target_clients':10,'slow_receiver_index':6,'executions':0,'errors':[],
            'interruptions':[],'resource_samples':[],'scope':'isolated test PostgreSQL/Redis, scoped Neo4j fault injection; loopback TLS',
            'latencies_ms':{},'observations':{},'status':'RUNNING'}
    clients=[httpx.AsyncClient(verify=stack.ssl,trust_env=False,timeout=15) for _ in users[:3]]
    headers={'Origin':stack.origin,'X-TradeGraph-Request':'1'}
    stop=asyncio.Event();notification_latency=deque(maxlen=20000);connection_latency=deque(maxlen=20000)
    response_latency=deque(maxlen=20000);reconnections=0;private_leaks=0
    tasks=[];last_refresh=0
    async def refresh():
        nonlocal last_refresh
        for client,user in zip(clients,users):
            response=await client.post(stack.origin+'/api/backend/login',headers=headers,json={k:user[k] for k in ('email','password')})
            response.raise_for_status()
        last_refresh=time.monotonic()
    async def socket_loop(index):
        nonlocal reconnections,private_leaks
        owner=index%3
        while not stop.is_set():
            try:
                response=await clients[owner].post(stack.origin+'/api/live/ticket',headers=headers)
                response.raise_for_status();ticket=response.json()['ticket']
                start=time.perf_counter()
                async with connect(stack.origin.replace('https:','wss:')+'/live/ws',ssl=stack.ssl,
                                   origin=stack.origin,subprotocols=['tradegraph.v1','ticket.'+ticket],
                                   max_queue=16,open_timeout=10) as ws:
                    connection_latency.append((time.perf_counter()-start)*1000);reconnections+=1
                    await ws.send(json.dumps({'type':'subscribe','instrument_ids':[iid]}))
                    until=time.monotonic()+45+(index%3)*5
                    while not stop.is_set() and time.monotonic()<until:
                        try:message=json.loads(await asyncio.wait_for(ws.recv(),2))
                        except TimeoutError:continue
                        if message['type']=='ping':await ws.send(json.dumps({'type':'pong'}));continue
                        notification_latency.append((datetime.now(timezone.utc)-datetime.fromisoformat(message['published_at'])).total_seconds()*1000)
                        # Trader 3 never owns orders in this scenario.
                        if owner==2 and message['type'] in ('order.changed','account.changed'):
                            private_leaks+=1
                        if index==6:await asyncio.sleep(.4)  # deliberately slower receiver
            except Exception as exc:
                # Transport loss during explicit restarts/outages is expected.
                report['observations'][type(exc).__name__]=report['observations'].get(type(exc).__name__,0)+1
                await asyncio.sleep(.5)
    async def await_settled(expected):
        deadline=time.monotonic()+20
        while time.monotonic()<deadline:
            rows=await asyncio.to_thread(db.query,'SELECT count(*) AS n FROM execution WHERE instrument_id=%s',(iid,))
            if rows[0]['n']==expected:return
            await asyncio.sleep(.02)
        raise RuntimeError('Settlement convergence timeout')
    async def interrupt(kind):
        start=time.monotonic()
        if kind=='neo4j':
            (stack.root/'neo4j-unavailable').touch()
            await asyncio.sleep(3)
            (stack.root/'neo4j-unavailable').unlink()
        elif kind=='redis':
            target=redis.Redis.from_url(settings.redis_url)
            pidfile=Path(settings.trader_credentials_file).parent/'redis.pid'
            if target.info('server')['process_id']!=int(pidfile.read_text()):raise RuntimeError('Test Redis PID mismatch')
            await asyncio.to_thread(target.shutdown,save=True)
            try:await asyncio.sleep(3)
            finally:
                from urllib.parse import urlsplit
                port=urlsplit(settings.redis_url).port
                subprocess.run(['redis-server','--bind','127.0.0.1','--port',str(port),'--dir',str(pidfile.parent),
                    '--appendonly','yes','--daemonize','yes','--pidfile',str(pidfile),'--logfile',str(pidfile.parent/'redis.log')],check=True)
                target.close()
        else:
            await asyncio.to_thread(stack.restart,kind)
        report['interruptions'].append({'kind':kind,'duration_seconds':time.monotonic()-start,
                                       'mode':'scoped handler fault' if kind=='neo4j' else 'owned service restart'})
    try:
        await refresh()
        for index in range(7):tasks.append(asyncio.create_task(socket_loop(index)))
        began=time.monotonic();next_sample=began;next_fault=began+60
        faults=iter(('neo4j','redis','frontend','proxy','backend'))
        fault_task=None
        while time.monotonic()-began<duration:
            if time.monotonic()-last_refresh>600:await refresh()
            if interruptions and time.monotonic()>=next_fault and fault_task is None:
                kind=next(faults,None)
                if kind:
                    # Backend restart happens between fully settled pairs only.
                    if kind=='backend':await interrupt(kind)
                    else:fault_task=asyncio.create_task(interrupt(kind))
                next_fault=time.monotonic()+max(60,duration/7)
            if fault_task and fault_task.done():
                await fault_task;fault_task=None
            # Pause new financial admissions only while transport/auth is offline.
            dependency_outage=fault_task is not None and kind in ('redis','frontend','proxy')
            if not dependency_outage:
                try:
                    buyer=report['executions']%2
                    for owner,side in ((buyer,'BUY'),(1-buyer,'SELL')):
                        start=time.perf_counter()
                        response=await clients[owner].post(stack.origin+'/api/backend/orders',headers={**headers,'Idempotency-Key':str(uuid4())},
                            json={'instrument_id':iid,'side':side,'price_ticks':'100','quantity':'1'})
                        response_latency.append((time.perf_counter()-start)*1000)
                        if response.status_code!=201:raise RuntimeError('Order rejected: '+str(response.status_code))
                    await await_settled(report['executions']+1);report['executions']+=1
                except Exception as exc:
                    report['errors'].append({'type':type(exc).__name__,'elapsed':time.monotonic()-began})
                    raise  # Never blindly retry an uncertain financial admission.
            if time.monotonic()>=next_sample:
                try:
                    metrics=(await clients[0].get(stack.backend+'/__test/metrics')).json()
                    samples=subprocess.check_output(['ps','-o','pid=,rss=,%cpu=','-p',','.join(str(p.pid) for p in stack.processes.values())],text=True)
                    report['resource_samples'].append({'elapsed':time.monotonic()-began,
                        'metrics':metrics,'processes':[dict(zip(('pid','rss_kib','cpu_percent'),line.split())) for line in samples.splitlines()]})
                except Exception as exc:report['observations']['sample_'+type(exc).__name__]=report['observations'].get('sample_'+type(exc).__name__,0)+1
                report['elapsed_seconds']=time.monotonic()-began
                private_json(output,report)
                next_sample=time.monotonic()+10
            await asyncio.sleep(.95)
        if fault_task:await fault_task
        stop.set()
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        # Let server receive disconnects and durable consumers converge.
        deadline=time.monotonic()+75
        while time.monotonic()<deadline:
            diagnostic=await asyncio.to_thread(diagnose,db)
            metrics=(await clients[0].get(stack.backend+'/__test/metrics')).json()
            pending=await asyncio.to_thread(db.query,'SELECT count(*) AS n FROM event_outbox o JOIN execution e ON e.id=o.execution_id WHERE e.instrument_id=%s AND completed_at IS NULL',(iid,))
            if pending[0]['n']==0 and metrics['clients']==0 and metrics['socket_tasks']==0:break
            await asyncio.sleep(.25)
        else:raise RuntimeError('Consumers or socket tasks did not converge')
        invariant_keys=('active_orders','volume_mismatches','escrow_mismatches','position_mismatches',
                        'duplicate_order_ids','execution_order_mismatches','missing_publication_intents')
        assert all(diagnostic[k]==0 for k in invariant_keys),diagnostic
        assert private_leaks==0
        assert metrics['financial_failure'] is False
        report['final_invariants']={k:diagnostic[k] for k in invariant_keys}
        report['final_socket_metrics']=metrics
        report['reconnections']=reconnections;report['private_leaks']=private_leaks
        report['latencies_ms']={'http':distribution(response_latency),'connect':distribution(connection_latency),
                                'notification':distribution(notification_latency),'settlement':distribution(metrics['settlement_ms'])}
        report['elapsed_seconds']=time.monotonic()-began
        report['status']='PASS'
    except BaseException:
        report['status']='FAILED'
        raise
    finally:
        stop.set()
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks,return_exceptions=True)
        for client in clients:await client.aclose()
        report['finished_at']=datetime.now(timezone.utc).isoformat();private_json(output,report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--caddy',required=True)
    parser.add_argument('--duration-seconds',type=int,default=1800)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--interruptions',action='store_true')
    parser.add_argument('--browser-module',help='Installed Playwright module path for real browser sessions')
    args=parser.parse_args()
    if not 30<=args.duration_seconds<=3600:parser.error('Duration must be 30..3600 seconds')
    settings=Settings.from_env()
    if not settings.postgres_db.startswith('tradegraph_test_'):raise ValueError('Isolated test database required')
    fixture=accounts.__wrapped__(SimpleNamespace(param='STANDARD'))
    users,iid=next(fixture)
    try:
        with ProductionTestStack(args.caddy,root=args.output.parent,backend_port=58100,next_port=53101,https_port=58543,http_port=58180) as stack:
            browser=None
            if args.browser_module:
                import base64, hashlib
                public_key=subprocess.check_output(['openssl','x509','-in',str(stack.root/'cert.pem'),'-pubkey','-noout'])
                der=subprocess.check_output(['openssl','pkey','-pubin','-outform','DER'],input=public_key)
                fixture_file=stack.root/'browser-fixture.json'
                browser_output=stack.root/'browser-results.json'
                private_json(fixture_file,{'origin':stack.origin,'users':[{k:u[k] for k in ('email','password')} for u in users[:3]],
                    'spki':base64.b64encode(hashlib.sha256(der).digest()).decode(),'duration':args.duration_seconds,'output':str(browser_output)})
                browser_env=dict(stack.env,TRADEGRAPH_PLAYWRIGHT_MODULE=args.browser_module,TRADEGRAPH_BROWSER_FIXTURE=str(fixture_file))
                browser=subprocess.Popen(['node',str(ROOT/'scripts/stability_browser.mjs')],env=browser_env,stdout=subprocess.DEVNULL,stderr=(stack.root/'browser.log').open('w'))
            try:
                report=asyncio.run(run(stack,users,iid,args.duration_seconds,args.output,interruptions=args.interruptions))
            finally:
                if browser:
                    browser.terminate()
                    try:browser.wait(timeout=25)
                    except subprocess.TimeoutExpired:browser.kill();browser.wait()
            if browser:
                report['browser']=json.loads(browser_output.read_text())
                if report['browser']['sessions']!=3 or report['browser']['fatal']:
                    report['status']='FAILED'
                    private_json(args.output,report)
                    raise RuntimeError('Browser stability checks failed; inspect private browser report')
            else:
                report['browser']='NOT_VERIFIED: supply --browser-module'
            private_json(args.output,report)
            print(json.dumps({'status':report['status'],'seconds':report['elapsed_seconds'],'executions':report['executions'],'artifact':str(args.output)}))
    finally:
        try:next(fixture)
        except StopIteration:pass


if __name__=='__main__':main()
