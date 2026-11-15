import asyncio
import json
import os
from pathlib import Path
from threading import Event
import time
from time import perf_counter_ns
from fastapi.testclient import TestClient
from backend.config import Settings
from backend.stores.postgres import Database
from backend.stores.neo4j_graph import Neo4jGraph
from backend.events.dispatcher import Dispatcher,DerivedWorker
from backend.matching.order_book import Order,OrderBook
from backend.api.main import create_app
from tests.integration.test_order_pipeline import accounts,login,order
from tests.benchmarks.test_matching_latency import distribution


def save(key,result):
    if not os.environ.get('TRADEGRAPH_ISOLATION_REPORT'): return
    path=Path(os.environ['TRADEGRAPH_ISOLATION_REPORT'])
    data=json.loads(path.read_text()) if path.exists() else {}
    data[key]=result
    path.write_text(json.dumps(data,indent=2))


def core_samples(count=2000):
    book=OrderBook()
    for i in range(count): book.submit(Order(i+1,'a',1,'SELL',100,1))
    incoming=[Order(count+i+1,'b',1,'BUY',100,1) for i in range(count)]
    samples=[]
    for item in incoming:
        start=perf_counter_ns();result=book.submit(item);samples.append(perf_counter_ns()-start)
        assert result.fills[0].quantity==1
    return distribution(samples)


def test_gated_real_graph_worker_does_not_block_core(accounts):
    users,_=accounts
    started,release,finished=Event(),Event(),Event()
    graph=Neo4jGraph(Settings.from_env(),Database(Settings.from_env()))
    def handler(_):
        started.set()
        assert release.wait(timeout=30)
        graph.rebuild([u['trader_id'] for u in users if u['trader_id']])
        finished.set()
    async def exercise():
        baseline=core_samples()
        worker=DerivedWorker('gated_graph',handler,Dispatcher(2));worker.start()
        start=perf_counter_ns();worker.publish(None)
        try:
            assert await asyncio.to_thread(started.wait,5)
            gated=core_samples()
            assert not finished.is_set()  # core completed before downstream release
            release.set()
            await asyncio.wait_for(worker.queue.join(),15)
            assert finished.is_set()
            return {'baseline_core_us':baseline,'gated_core_us':gated,
                    'downstream_completion_ms':(perf_counter_ns()-start)/1e6,
                    'core_completed_while_graph_gated':True,
                    'interpretation':'Structural independence proven; distributions may vary due to shared CPU scheduling.'}
        finally:
            release.set();await worker.stop()
    try: result=asyncio.run(exercise())
    finally: graph.close()
    save('gated_graph',result)


def test_native_api_settlement_latency_with_slow_graph(accounts):
    users,instrument=accounts
    results={}
    for slow in (False,True):
        label='slow_graph' if slow else 'baseline'
        end_to_end=[];core=[];settlement=[]
        with TestClient(create_app()) as client:
            a,b=login(client,users[0]),login(client,users[1])
            db=client.app.state.database
            original_submit=client.app.state.service.engine.submit
            def measured_submit(incoming):
                start=perf_counter_ns()
                try: return original_submit(incoming)
                finally: core.append(perf_counter_ns()-start)
            client.app.state.service.engine.submit=measured_submit
            original_settle=db.settle
            def measured_settle(event):
                start=perf_counter_ns()
                try: return original_settle(event)
                finally: settlement.append(perf_counter_ns()-start)
            db.settle=measured_settle
            if slow:
                original_graph=client.app.state.graph.apply
                def delayed_graph(event):
                    time.sleep(.05)
                    return original_graph(event)
                client.app.state.graph.apply=delayed_graph
            base=db.query('SELECT count(*) AS n FROM execution WHERE instrument_id=%s',(instrument,))[0]['n']
            for i in range(20):
                start=perf_counter_ns()
                assert client.post('/orders',headers=a,json=order(instrument)).status_code==201
                assert client.post('/orders',headers=b,json=order(instrument,'SELL')).status_code==201
                deadline=time.monotonic()+10
                while True:
                    count=db.query('SELECT count(*) AS n FROM execution WHERE instrument_id=%s',(instrument,))[0]['n']
                    if count==base+i+1: break
                    assert time.monotonic()<deadline
                    time.sleep(.001)
                end_to_end.append(perf_counter_ns()-start)
            before_drain=perf_counter_ns()
        drain=(perf_counter_ns()-before_drain)/1e6
        assert len(settlement)==20 and len(core)==40
        results[label]={'core_us':distribution(core),'settlement_transaction_ms':distribution(settlement,1e6),
                        'api_pair_to_settled_ms':distribution(end_to_end,1e6),'shutdown_derived_drain_ms':drain,
                        'injected_graph_delay_ms':50 if slow else 0}
    results['transport']='in-process ASGI HTTP plus real native services; excludes external TCP/client latency'
    save('native_api',results)
