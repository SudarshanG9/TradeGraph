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
from threading import get_ident
from uuid import uuid4

import bcrypt
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


def test_human_bot_native_trading_finance_derived_stores_and_safe_stop(monkeypatch):
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
    maker_fee = ceil(Fraction(100) * Fraction(tier[1]) / 10000)
    taker_fee = ceil(Fraction(100) * Fraction(tier[2]) / 10000)
    reserve_fee = lambda value: ceil(Fraction(value) * max(Fraction(tier[1]), Fraction(tier[2])) / 10000)
    try:
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
            conn.execute('DELETE FROM execution WHERE instrument_id=%s',(iid,))
            for table in ('position','order_history','order','kyc_profile','margin_account','trader'):
                key = 'id' if table == 'trader' else 'trader_id'
                conn.execute(f'DELETE FROM public."{table}" WHERE {key}=ANY(%s)',(owned,))
            conn.execute('DELETE FROM user_account WHERE id=ANY(%s)',([u['id'] for u in users],))
            conn.execute('DELETE FROM instrument WHERE id=%s',(iid,))
