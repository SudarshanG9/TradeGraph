"""Reproducible human/bot proof on real PostgreSQL, Redis and Neo4j.

All identities and the instrument belong to this fixture. A test-only namespace
substitution exercises the production allowlist validation without touching the
persistent bots. No matching/settlement operation is mocked. The strategy seam
makes the first quote deterministic. History persists through stop and restart,
then only these isolated test fixtures are removed.
"""
from dataclasses import replace
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import secrets
from concurrent.futures import ThreadPoolExecutor
from threading import Event, get_ident
from uuid import uuid4

import bcrypt
import pytest
from fastapi.testclient import TestClient

from backend.api.main import create_app
from backend.events.trade_event import TradeEvent
from backend.simulator.agents import TradingAgent, PlaceOrderAction, HoldAction
from scripts.seed_live_bots import load_bot_specs
from scripts.verify_schema import db_connect
from tests.integration.test_order_pipeline import login, order
from tests.integration.test_polyglot import wait_until


def ceil(value):
    return -(-value.numerator // value.denominator)


class ProofQuoteAgent(TradingAgent):
    def __init__(self, *args, quote=False):
        super().__init__(*args)
        self.quote = quote
        self.issued = False

    def decide(self, observation, account_state, active_orders):
        if self.quote and not self.issued:
            self.issued = True
            return PlaceOrderAction(self.instrument_id, 'SELL', 100, 2)
        return HoldAction('Deterministic native proof')


def proof_factory(spec, tid, iid, seed):
    return ProofQuoteAgent(tid, iid, seed, quote=spec.name == 'Synthetic Live mm-01')


@pytest.fixture
def live_fixture(monkeypatch):
    run = uuid4().hex[:12]
    password = secrets.token_urlsafe(24)
    hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    symbol = 'LIVE' + run
    users = []
    bot_ids = []
    test_specs = tuple(replace(spec, email=f'live-proof-{index}-{run}@tradegraph.test')
                       for index,spec in enumerate(load_bot_specs()))
    monkeypatch.setattr('backend.simulator.live_supervisor.load_bot_specs', lambda: test_specs)
    with db_connect() as conn:
        tier = conn.execute("SELECT id,maker_fee_bps,taker_fee_bps FROM fee_tier WHERE tier_name='STANDARD'").fetchone()
        desk = conn.execute("SELECT id FROM desk WHERE name='Equities'").fetchone()[0]
        iid = conn.execute('INSERT INTO instrument(symbol,tick_size,lot_size) VALUES (%s,1,1) RETURNING id', (symbol,)).fetchone()[0]
        for role in ('TRADER', 'COMPLIANCE_ADMIN'):
            email = f'live-proof-{role.lower()}-{run}@tradegraph.test'
            uid = conn.execute('INSERT INTO user_account(email,password_hash,role) VALUES (%s,%s,%s) RETURNING id', (email,hashed,role)).fetchone()[0]
            tid = None
            if role == 'TRADER':
                tid = conn.execute("INSERT INTO trader(user_account_id,full_name) VALUES (%s,'Synthetic live proof human') RETURNING id",(uid,)).fetchone()[0]
                conn.execute('INSERT INTO margin_account(trader_id,cash_balance,fee_tier_id) VALUES (%s,1000000,%s)', (tid,tier[0]))
                conn.execute('INSERT INTO kyc_profile(trader_id,pan_hash) VALUES (%s,%s)', (tid,hashlib.sha256(email.encode()).hexdigest()))
            users.append(dict(id=uid,trader_id=tid,email=email,password=password))
        for spec in test_specs:
            uid = conn.execute("INSERT INTO user_account(email,password_hash,role) VALUES (%s,%s,'TRADER') RETURNING id",(spec.email,hashed)).fetchone()[0]
            tid = conn.execute('INSERT INTO trader(user_account_id,desk_id,full_name) VALUES (%s,%s,%s) RETURNING id',(uid,desk,spec.name)).fetchone()[0]
            conn.execute('INSERT INTO margin_account(trader_id,cash_balance,fee_tier_id) VALUES (%s,1000000,%s)',(tid,tier[0]))
            conn.execute('INSERT INTO kyc_profile(trader_id,pan_hash) VALUES (%s,%s)',(tid,spec.pan_hash))
            bot_ids.append(tid)
            users.append(dict(id=uid,trader_id=tid,email=spec.email))
        bot = (bot_ids[0],1_000_000,0)
    try:
        from scripts.setup_database_identity import provision_test_traders
        provision_test_traders([u['trader_id'] for u in users if u['trader_id']])
        yield dict(users=users, iid=iid, symbol=symbol, bot=bot, tier=tier, test_specs=test_specs)
    finally:
        from backend.config import Settings
        from backend.stores.postgres import Database
        from backend.stores.redis_depth import RedisDepth
        from backend.stores.neo4j_graph import Neo4jGraph
        owned = [u['trader_id'] for u in users if u['trader_id']]
        # Refuse cleanup if any counterparty or instrument user is outside this fixture.
        with db_connect() as conn:
            external = conn.execute('''SELECT count(*) FROM execution WHERE instrument_id=%s
                AND NOT(buy_trader_id=ANY(%s) AND sell_trader_id=ANY(%s))''',(iid,owned,owned)).fetchone()[0]
            assert external == 0, 'External counterparty: cleanup refused'
            assert conn.execute('SELECT count(*) FROM public."order" WHERE instrument_id=%s AND NOT(trader_id=ANY(%s))',(iid,owned)).fetchone()[0] == 0
        settings = Settings.from_env()
        graph_store = Neo4jGraph(settings,Database(settings))
        try:
            graph_store.remove_owned_nodes(owned)
        finally:
            graph_store.close()
        cache = RedisDepth(settings.redis_url)
        try:
            cache.client.delete(*cache.keys(symbol))
        finally:
            cache.close()
        with db_connect() as conn:
            conn.execute('DELETE FROM regime_snapshot WHERE instrument_id=%s',(iid,))
            conn.execute('DELETE FROM order_request_identity WHERE trader_id=ANY(%s)',(owned,))
            conn.execute('DELETE FROM execution WHERE instrument_id=%s',(iid,))
            for table in ('position','order_history','order','kyc_profile','margin_account','trader'):
                key = 'id' if table == 'trader' else 'trader_id'
                conn.execute(f'DELETE FROM public."{table}" WHERE {key}=ANY(%s)',(owned,))
            conn.execute('DELETE FROM user_account WHERE id=ANY(%s)',([u['id'] for u in users],))
            conn.execute('DELETE FROM instrument WHERE id=%s',(iid,))
        provision_test_traders(owned,remove=True)


def test_human_bot_native_trading_finance_derived_stores_and_safe_stop(live_fixture):
    users, iid, symbol, bot, tier, test_specs = (live_fixture[k] for k in ('users', 'iid', 'symbol', 'bot', 'tier', 'test_specs'))
    maker_fee = ceil(Fraction(100) * Fraction(tier[1]) / 10000)
    taker_fee = ceil(Fraction(100) * Fraction(tier[2]) / 10000)
    reserve_fee = lambda value: ceil(Fraction(value) * max(Fraction(tier[1]), Fraction(tier[2])) / 10000)
    with TestClient(create_app()) as client:
        human, admin = login(client,users[0]), login(client,users[1])
        supervisor = client.app.state.live_simulator
        supervisor.agent_factory = proof_factory
        service = client.app.state.service
        owner = service.engine.owner
        # Verify admission/matching stay on the preexisting owner thread.
        original_admit = service.admit
        async def checked_admit(*args, **kwargs):
            assert get_ident() == owner
            return await original_admit(*args, **kwargs)
        service.admit = checked_admit
        result = client.post('/admin/simulator/start',headers=admin,json={
            'instrument_ids':[iid], 'bot_count':8, 'orders_per_second':5,
            'volatility':'low', 'seed':20261115, 'max_duration_seconds':30})
        assert result.status_code == 200, result.text
        assert result.json()['active_bots'] == 8
        assert supervisor.coordinator is service
        book_url = f'/market/{symbol}/book'
        initial_book = wait_until(lambda:client.get(book_url,headers=human).json(),
            lambda r:r.get('asks') == [{'price_ticks':100,'quantity':2}])
        bot_orders = service.database.query('SELECT * FROM public."order" WHERE trader_id=%s AND instrument_id=%s', (bot[0],iid))
        assert len(bot_orders) == 1
        quote = bot_orders[0]
        bot_reserved = service.database.query('SELECT cash_balance,escrow_balance FROM margin_account WHERE trader_id=%s', (bot[0],))[0]
        assert bot_reserved == dict(cash_balance=bot[1]-200-reserve_fee(200), escrow_balance=200+reserve_fee(200))
        # This human resting bid must survive simulator stop unchanged.
        resting = client.post('/orders',headers=human,json=order(iid,'BUY',50,1))
        assert resting.status_code == 201
        resting_id = resting.json()['order_id']
        crossing = client.post('/orders',headers=human,json=order(iid,'BUY',110,1))
        assert crossing.status_code == 201, crossing.text
        human_order = crossing.json()['order_id']
        executions = wait_until(lambda:client.get(f'/market/{symbol}/trades',headers=human).json(),lambda r:len(r.get('items',[])) == 1)
        execution = executions['items'][0]
        assert (execution['price_ticks'],execution['quantity'],execution['buy_order_id'],execution['sell_order_id']) == (100,1,human_order,quote['id'])
        assert execution['buy_trader_id'] == str(users[0]['trader_id'])
        assert execution['sell_trader_id'] == str(bot[0])
        wait_until(lambda:client.get('/admin/simulator/status',headers=admin).json(), lambda r:r['committed_executions'] == 1)
        human_partial = client.get('/account/me',headers=human).json()
        assert (human_partial['cash_balance'],human_partial['escrow_balance']) == (1_000_000-100-taker_fee-50-reserve_fee(50),50+reserve_fee(50))
        assert human_partial['positions'] == [{'instrument_id':iid,'net_quantity':1,'realized_pnl':0,'pnl_basis':'gross'}]
        partial = service.database.query('SELECT status,filled_quantity FROM public."order" WHERE id=%s',(quote['id'],))[0]
        assert partial == dict(status='PARTIAL',filled_quantity=1)
        post_fill_book = wait_until(lambda:client.get(book_url,headers=human).json(),
            lambda r:r.get('version') == service.version and r.get('asks') == [{'price_ticks':100,'quantity':1}])
        # Read-only graph query: only the normal asynchronous worker may
        # deliver the committed relationship. The proof never rebuilds it.
        graph = wait_until(lambda:client.app.state.graph.run('''MATCH (a:Trader {id:$a})-[r:EXECUTED_AGAINST]->(b:Trader {id:$b})
            RETURN r.trade_count AS trade_count,r.total_notional AS total_notional''',
            {'a':str(users[0]['trader_id']),'b':str(bot[0])}), lambda r:bool(r) and r[0]['trade_count']==1)
        assert graph == [dict(trade_count=1,total_notional=100)]
        regimes = wait_until(lambda:service.database.named('similar', {'features':'[0,0,0,1,0,0]','instrument_id':iid,'limit':10}), lambda rows:bool(rows))
        analytics = client.get(f'/market/{symbol}/analytics',headers=human).json()
        assert (analytics['band_volume'],analytics['vwap_ticks']) == (1,'100')
        stop = client.post('/admin/simulator/stop',headers=admin)
        assert stop.status_code == 200, stop.text
        stopped = stop.json()
        assert stopped['state'] == 'STOPPED' and stopped['active_bot_orders'] == 0
        assert stopped['orders_accepted'] == stopped['orders_cancelled'] == stopped['committed_executions'] == 1
        assert supervisor.task.done()
        bot_final = service.database.query('SELECT cash_balance,escrow_balance FROM margin_account WHERE trader_id=%s',(bot[0],))[0]
        assert bot_final == dict(cash_balance=bot[1]+100-maker_fee,escrow_balance=0)
        bot_position = service.database.query('SELECT net_quantity,realized_pnl FROM position WHERE trader_id=%s AND instrument_id=%s',(bot[0],iid))[0]
        assert bot_position == dict(net_quantity=-1,realized_pnl=0)
        terminal = service.database.query('SELECT status,filled_quantity FROM public."order" WHERE id=%s',(quote['id'],))[0]
        assert terminal == dict(status='CANCELLED',filled_quantity=1)
        human_resting = service.database.query('SELECT status,quantity,filled_quantity FROM public."order" WHERE id=%s',(resting_id,))[0]
        assert human_resting == dict(status='OPEN',quantity=1,filled_quantity=0)
        stop_book = wait_until(lambda:client.get(book_url,headers=human).json(),
            lambda r:r.get('version')==service.version and r.get('asks')==[] and r.get('bids')==[{'price_ticks':50,'quantity':1}])
        # Only the human's own cancellation closes its remaining reservation.
        assert client.post(f'/orders/{resting_id}/cancel',headers=human).status_code == 200
        human_final = client.get('/account/me',headers=human).json()
        assert (human_final['cash_balance'],human_final['escrow_balance']) == (1_000_000-100-taker_fee,0)
        event_row = service.database.query('SELECT * FROM execution WHERE id=%s',(execution['id'],))[0]
        replay = TradeEvent(event_row['id'],iid,human_order,quote['id'],users[0]['trader_id'],bot[0],100,1,human_order,event_row['executed_at'])
        assert service.database.settle(replay) is False
        assert client.get('/account/me',headers=human).json() == human_final
        evidence = dict(human_email=users[0]['email'],human_trader_id=users[0]['trader_id'],
            bot_email=test_specs[0].email,bot_trader_id=bot[0],instrument_id=iid,symbol=symbol,
            quote_order_id=quote['id'],human_order_id=human_order,execution=execution,
            bot_initial_cash=bot[1],bot_reserved=bot_reserved,bot_final=bot_final,
            human_partial=human_partial,human_final=human_final,bot_position=bot_position,
            maker_fee=maker_fee,taker_fee=taker_fee,redis_initial=initial_book,
            redis_after_fill=post_fill_book,redis_after_stop=stop_book,neo4j=graph,
            regime_snapshot_id=regimes[0]['id'],analytics=analytics,stop=stopped,
            history_preserved_through_stop=True,settlement_replay_applied=False,
            test_namespace='isolated fixture identities; production allowlist unchanged')
        Path('/tmp/tradegraph-live-proof.json').write_text(json.dumps(evidence,default=str,indent=2)+'\n')
    # A clean restart is STOPPED and rehydrates genuine settled statistics.
    with TestClient(create_app()) as restarted:
        assert restarted.app.state.live_simulator.state.value == 'STOPPED'
        headers = login(restarted,users[0])
        assert restarted.get(f'/market/{symbol}/analytics',headers=headers).json()['band_volume'] == 1


def test_native_bot_stp_funds_rejection_and_outstanding_limits(live_fixture):
    data = live_fixture
    with TestClient(create_app()) as client:
        s = client.app.state.live_simulator
        s.agent_factory = proof_factory
        admin = login(client,data['users'][1])
        assert client.post('/admin/simulator/start',headers=admin,json={'instrument_ids':[data['iid']]}).status_code == 200
        wait_until(lambda:client.get('/admin/simulator/status',headers=admin).json(), lambda r:r['orders_accepted']==1)
        async def exercise():
            await s._reconcile()
            # An injected self-cross reaches real coordinator STP. Strategies
            # normally HOLD on this input; no bypass of the financial machinery.
            await s._execute_action(s.agents[0],PlaceOrderAction(data['iid'],'BUY',100,1))
            await s._reconcile()
            await s._execute_action(s.agents[3],PlaceOrderAction(data['iid'],'BUY',1_000_000,1))
            assert s.metrics['orders_rejected'] == 1
            for price in (90,89,88,87):
                await s._execute_action(s.agents[1],PlaceOrderAction(data['iid'],'BUY',price,1))
                await s._reconcile()
            assert len(s._orders_for(s.agents[1])) == 4
            with pytest.raises(ValueError,match='INVALID_AGENT_ORDER'):
                await s._execute_action(s.agents[1],PlaceOrderAction(data['iid'],'BUY',86,1))
        client.portal.call(exercise)
        result = client.post('/admin/simulator/stop',headers=admin).json()
        assert result['state'] == 'STOPPED' and result['active_bot_orders'] == result['committed_executions'] == 0
        rows = s.database.query('SELECT cash_balance,escrow_balance FROM margin_account WHERE trader_id=ANY(%s)',
            ([u['trader_id'] for u in data['users'] if u['trader_id']],))
        assert all(r == dict(cash_balance=1_000_000,escrow_balance=0) for r in rows)
        cancelled = s.database.query('SELECT status,filled_quantity FROM public."order" WHERE instrument_id=%s',(data['iid'],))
        assert len(cancelled) == 6 and all(r == dict(status='CANCELLED',filled_quantity=0) for r in cancelled)


def test_native_stop_waits_for_committing_reservation(live_fixture):
    data = live_fixture
    committed, release = Event(), Event()
    with TestClient(create_app()) as client:
        s = client.app.state.live_simulator
        s.agent_factory = proof_factory
        admin = login(client,data['users'][1])
        original = s.database.reserve
        def delayed_ack(*args):
            row = original(*args)  # Real COMMIT precedes the gate.
            committed.set()
            assert release.wait(10)
            return row
        s.database.reserve = delayed_ack
        try:
            assert client.post('/admin/simulator/start',headers=admin,json={'instrument_ids':[data['iid']]}).status_code == 200
            assert committed.wait(5)
            with ThreadPoolExecutor(1) as pool:
                stopping = pool.submit(lambda:client.post('/admin/simulator/stop',headers=admin))
                try:
                    wait_until(lambda:client.get('/admin/simulator/status',headers=admin).json(),lambda r:r['state']=='STOPPING')
                    assert not stopping.done()
                    assert client.post('/admin/simulator/start',headers=admin,json={'instrument_ids':[data['iid']]}).status_code == 409
                finally:
                    release.set()
                result = stopping.result(timeout=10).json()
                assert result['state'] == 'STOPPED'
                assert result['orders_accepted'] == result['orders_cancelled'] == 1
                assert result['active_bot_orders'] == 0
        finally:
            release.set()
            s.database.reserve = original


def test_native_stop_waits_for_settlement_acknowledgement(live_fixture):
    data = live_fixture
    committed, release = Event(), Event()
    with TestClient(create_app()) as client:
        s = client.app.state.live_simulator
        s.agent_factory = proof_factory
        human, admin = login(client,data['users'][0]), login(client,data['users'][1])
        original = s.database.settle
        def delayed_ack(*args):
            applied = original(*args)  # Real settlement transaction already committed.
            committed.set()
            assert release.wait(10)
            return applied
        s.database.settle = delayed_ack
        try:
            assert client.post('/admin/simulator/start',headers=admin,json={'instrument_ids':[data['iid']]}).status_code == 200
            wait_until(lambda:client.get('/admin/simulator/status',headers=admin).json(), lambda r:r['orders_accepted']==1)
            assert client.post('/orders',headers=human,json=order(data['iid'],'BUY',100,1)).status_code == 201
            assert committed.wait(5)
            with ThreadPoolExecutor(1) as pool:
                stopping = pool.submit(lambda:client.post('/admin/simulator/stop',headers=admin))
                try:
                    status = wait_until(lambda:client.get('/admin/simulator/status',headers=admin).json(),lambda r:r['state']=='STOPPING')
                    assert not stopping.done() and status['committed_executions'] == 1
                finally:
                    release.set()
                result = stopping.result(timeout=10).json()
                assert result['state'] == 'STOPPED' and result['committed_executions'] == 1
                assert result['active_bot_orders'] == 0 and s.coordinator.worker.pending is None
        finally:
            release.set()
            s.database.settle = original


@pytest.mark.parametrize('dependency', ['redis', 'neo4j'])
def test_live_derived_outage_preserves_sql_and_retries_real_delivery(live_fixture, dependency):
    import redis
    from neo4j import GraphDatabase
    data = live_fixture
    with TestClient(create_app()) as client:
        s = client.app.state.live_simulator
        s.agent_factory = proof_factory
        human, admin = login(client,data['users'][0]), login(client,data['users'][1])
        assert client.post('/admin/simulator/start',headers=admin,json={'instrument_ids':[data['iid']]}).status_code == 200
        wait_until(lambda:client.get(f'/market/{data["symbol"]}/book',headers=human).json(),lambda r:bool(r.get('asks')))
        if dependency == 'redis':
            store, attribute = client.app.state.depth, 'client'
            broken = redis.Redis.from_url('redis://127.0.0.1:1/0',socket_connect_timeout=1,socket_timeout=1)
        else:
            store, attribute = client.app.state.graph, 'driver'
            broken = GraphDatabase.driver('bolt://127.0.0.1:1',connection_timeout=1,max_connection_pool_size=1)
        original = getattr(store,attribute)
        setattr(store,attribute,broken)
        try:
            assert client.post('/orders',headers=human,json=order(data['iid'],'BUY',100,1)).status_code == 201
            worker = s.coordinator.derived[dependency]
            wait_until(lambda:worker.failed,lambda r:bool(r))
            status = client.get('/admin/simulator/status',headers=admin).json()
            assert status['derived_workers'][dependency] == 'retrying'
            assert status['committed_executions'] == 1
            if dependency == 'redis':
                assert client.get(f'/market/{data["symbol"]}/book',headers=human).status_code == 503
            stopped = client.post('/admin/simulator/stop',headers=admin).json()
            assert stopped['state'] == 'STOPPED' and stopped['active_bot_orders'] == 0
            assert stopped['derived_workers'][dependency] == 'retrying'
            assert s.database.query('SELECT count(*) AS n FROM execution WHERE instrument_id=%s',(data['iid'],))[0]['n'] == 1
        finally:
            setattr(store,attribute,original)
            broken.close()
        # Existing worker retries its retained real job; no manual cache/graph write.
        wait_until(lambda:worker.failed,lambda r:r is None)
        if dependency == 'redis':
            wait_until(lambda:client.get(f'/market/{data["symbol"]}/book',headers=human).json(),
                lambda r:r.get('version')==s.coordinator.version and r.get('asks')==[])
        else:
            wait_until(lambda:client.app.state.graph.run('''MATCH (a:Trader {id:$a})-[r:EXECUTED_AGAINST]->(b:Trader {id:$b})
                RETURN r.trade_count AS n''',{'a':str(data['users'][0]['trader_id']),'b':str(data['bot'][0])}),
                lambda r:bool(r) and r[0]['n']==1)


def test_verified_error_recovery_preserves_terminal_bot_session_and_human_orders(live_fixture):
    from backend.simulator.live_supervisor import SimulationState
    users,iid=live_fixture['users'],live_fixture['iid']
    with TestClient(create_app()) as client:
        human,admin=login(client,users[0]),login(client,users[1])
        supervisor=client.app.state.live_simulator;supervisor.agent_factory=proof_factory
        assert client.post('/admin/simulator/recover',headers=human).status_code==403
        config={'instrument_ids':[iid],'bot_count':4,'orders_per_second':5,'max_duration_seconds':30}
        assert client.post('/admin/simulator/start',headers=admin,json=config).status_code==200
        wait_until(lambda:client.get('/admin/simulator/status',headers=admin).json(),lambda r:r['orders_accepted']>=1)
        oid=client.post('/orders',headers=human,json=order(iid,'BUY',50)).json()['order_id']
        assert client.post('/admin/simulator/stop',headers=admin).json()['state']=='STOPPED'
        old=supervisor.task
        async def pressure_error():
            supervisor.state=SimulationState.ERROR;supervisor.last_error='injected transient pressure after safe cleanup'
        client.portal.call(pressure_error)
        result=client.post('/admin/simulator/recover',headers=admin)
        assert result.status_code==200 and result.json()['state']=='STOPPED'
        assert supervisor.task is old and old.done()
        assert client.get(f'/orders/{oid}',headers=human).json()['status']=='OPEN'
        assert client.post('/admin/simulator/start',headers=admin,json=config).status_code==200
        assert supervisor.task is not old
        assert client.post('/admin/simulator/stop',headers=admin).json()['state']=='STOPPED'
        assert client.post(f'/orders/{oid}/cancel',headers=human).status_code==200
