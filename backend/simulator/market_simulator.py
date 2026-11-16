"""Deterministic API scenario against real native stores, with scoped fixture cleanup."""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timedelta,timezone
from decimal import Decimal,localcontext
from fractions import Fraction
import hashlib
import itertools
import json
import random
import secrets
import time
from uuid import uuid4
import bcrypt
from fastapi.testclient import TestClient
from psycopg.errors import UniqueViolation
from backend.api.main import create_app
from backend.config import Settings
from backend.events.trade_event import TradeEvent
from backend.stores.postgres import Database,query_text
from backend.stores.regimes import Regimes
from backend.stores.redis_depth import RedisDepth
from backend.stores.neo4j_graph import Neo4jGraph
from scripts.verify_schema import db_connect


def ceil_exact(value): return -(-value.numerator//value.denominator)


def round_minor(value):
    return (1 if value>=0 else -1)*((2*abs(value.numerator)+value.denominator)//(2*value.denominator))


def bounded(callback,predicate,timeout=15):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        result=callback()
        if predicate(result): return result
        time.sleep(.01)
    raise AssertionError('Native pipeline did not converge within timeout')


class DemoData:
    def fingerprint(self):
        with db_connect() as conn:
            rows=[]
            for table in ('user_account','trader','margin_account','position','instrument'):
                if table=='user_account': query='SELECT * FROM user_account WHERE id=ANY(%s) ORDER BY id'; ids=self.original_users
                elif table=='instrument': query='SELECT * FROM instrument WHERE id=ANY(%s) ORDER BY id'; ids=self.original_instruments
                else:
                    key='id' if table=='trader' else 'trader_id'
                    query=f'SELECT * FROM {table} WHERE {key}=ANY(%s) ORDER BY {key}'
                    if table=='position': query+=',instrument_id'
                    ids=self.original_traders
                rows.append(conn.execute(query,(ids,)).fetchall())
        return hashlib.sha256(json.dumps(rows,default=str,sort_keys=True).encode()).hexdigest()

    def __enter__(self):
        self.settings=Settings.from_env();self.db=Database(self.settings)
        self.users=[];self.instruments=[]
        prefix='TG'+uuid4().hex[:8]
        trader_password=secrets.token_urlsafe(24); admin_password=secrets.token_urlsafe(24)
        with db_connect() as conn:
            self.original_users=[r[0] for r in conn.execute('SELECT id FROM user_account')]
            self.original_traders=[r[0] for r in conn.execute('SELECT id FROM trader')]
            self.original_instruments=[r[0] for r in conn.execute('SELECT id FROM instrument')]
        self.before=self.fingerprint()
        with db_connect() as conn:
            tier=conn.execute("SELECT id,maker_fee_bps,taker_fee_bps FROM fee_tier WHERE tier_name='STANDARD'").fetchone()
            self.maker,self.taker=Fraction(tier[1]),Fraction(tier[2])
            desk=conn.execute("SELECT id FROM desk WHERE name='Equities'").fetchone()[0]
            for name in ('Alice','Bob','Carol','Race','Admin'):
                role='COMPLIANCE_ADMIN' if name=='Admin' else 'TRADER'
                password=admin_password if name=='Admin' else trader_password
                uid=conn.execute('INSERT INTO user_account(email,password_hash,role) VALUES (%s,%s,%s) RETURNING id',
                    (f'simulation-{uuid4()}@tradegraph.test',bcrypt.hashpw(password.encode(),bcrypt.gensalt()).decode(),role)).fetchone()[0]
                tid=None;cash=100000 if name=='Race' else 1000000
                email=conn.execute('SELECT email FROM user_account WHERE id=%s',(uid,)).fetchone()[0]
                if role=='TRADER':
                    tid=conn.execute('INSERT INTO trader(user_account_id,desk_id,full_name) VALUES (%s,%s,%s) RETURNING id',(uid,desk,'Simulation '+name)).fetchone()[0]
                    conn.execute('INSERT INTO margin_account(trader_id,cash_balance,fee_tier_id) VALUES (%s,%s,%s)',(tid,cash,tier[0]))
                    conn.execute('INSERT INTO kyc_profile(trader_id,pan_hash) VALUES (%s,%s)',(tid,hashlib.sha256(str(tid).encode()).hexdigest()))
                self.users.append({'id':uid,'trader_id':tid,'name':name,'role':role,'email':email,'password':password,'initial_cash':cash})
            for index,(tick,lot) in enumerate(((1,1),(5,10),(10,5),(1,1))):
                symbol=prefix+'_'+str(index)
                iid=conn.execute('INSERT INTO instrument(symbol,tick_size,lot_size,is_active) VALUES (%s,%s,%s,%s) RETURNING id',(symbol,tick,lot,index!=3)).fetchone()[0]
                self.instruments.append({'id':iid,'symbol':symbol,'tick_size':tick,'lot_size':lot})
        return self

    def __exit__(self,kind,value,tb):
        tids=[u['trader_id'] for u in self.users if u['trader_id']]
        iids=[i['id'] for i in self.instruments]
        errors=[]
        graph=Neo4jGraph(self.settings,self.db)
        try: graph.remove_owned_nodes(tids)
        except Exception as exc: errors.append(type(exc).__name__)
        finally: graph.close()
        depth=RedisDepth(self.settings.redis_url)
        try:
            for instrument in self.instruments: depth.client.delete(*depth.keys(instrument['symbol']))
        except Exception as exc: errors.append(type(exc).__name__)
        finally: depth.close()
        with db_connect() as conn:
            external=conn.execute('SELECT count(*) FROM execution WHERE (buy_trader_id=ANY(%s) OR sell_trader_id=ANY(%s)) AND NOT(buy_trader_id=ANY(%s) AND sell_trader_id=ANY(%s))',(tids,tids,tids,tids)).fetchone()[0]
            if external: raise RuntimeError('Unexpected external counterparty: operator reconciliation required; cleanup refused')
            conn.execute('DELETE FROM regime_snapshot WHERE instrument_id=ANY(%s)',(iids,))
            conn.execute('DELETE FROM market_disclosure WHERE instrument_id=ANY(%s)',(iids,))
            conn.execute('DELETE FROM order_request_identity WHERE trader_id=ANY(%s)',(tids,))
            conn.execute('DELETE FROM execution WHERE buy_trader_id=ANY(%s) OR sell_trader_id=ANY(%s)',(tids,tids))
            for table in ('position','order_history','order','kyc_profile','margin_account','trader'):
                key='id' if table=='trader' else 'trader_id'
                conn.execute(f'DELETE FROM public."{table}" WHERE {key}=ANY(%s)',(tids,))
            conn.execute('DELETE FROM user_account WHERE id=ANY(%s)',([u['id'] for u in self.users],))
            conn.execute('DELETE FROM instrument WHERE id=ANY(%s)',(iids,))
        if self.fingerprint()!=self.before: raise AssertionError('Existing user/reference data changed')
        if errors: raise RuntimeError('Scoped derived cleanup failed: '+','.join(errors))


def verify_accounts(data):
    tids=[u['trader_id'] for u in data.users if u['trader_id']]
    events=data.db.query('SELECT * FROM execution WHERE buy_trader_id=ANY(%s) OR sell_trader_id=ANY(%s) ORDER BY id',(tids,tids))
    cash={u['trader_id']:u['initial_cash'] for u in data.users if u['trader_id']}
    tick={i['id']:i['tick_size'] for i in data.instruments}
    fees=defaultdict(Fraction);owners={};positions={};pair_counts=defaultdict(int);pair_values=defaultdict(int)
    for e in events:
        value=e['price_ticks']*tick[e['instrument_id']]*e['quantity']
        pair=(e['buy_trader_id'],e['sell_trader_id']);pair_counts[pair]+=1;pair_values[pair]+=value
        for side in ('buy','sell'):
            who=e[side+'_trader_id'];oid=e[side+'_order_id'];owners[oid]=who
            rate=data.taker if oid==max(e['buy_order_id'],e['sell_order_id']) else data.maker
            fees[oid]+=Fraction(value)*rate/10000
            cash[who]+= -value if side=='buy' else value
            key=(who,e['instrument_id']);q,average,pnl=positions.get(key,(0,Fraction(0),Fraction(0)))
            delta=e['quantity']*(1 if side=='buy' else -1);price=Fraction(e['price_ticks']*tick[e['instrument_id']])
            if not q: average=price
            elif q*delta>0: average=(average*abs(q)+price*abs(delta))/(abs(q)+abs(delta))
            else:
                pnl+=min(abs(q),abs(delta))*(price-average)*(1 if q>0 else -1)
                if abs(delta)>abs(q): average=price
            q+=delta
            if not q: average=Fraction(0)
            positions[key]=(q,average,pnl)
    for oid,fee in fees.items(): cash[owners[oid]]-=ceil_exact(fee)
    actual=data.db.query('SELECT trader_id,cash_balance,escrow_balance FROM margin_account WHERE trader_id=ANY(%s)',(tids,))
    assert all(row['cash_balance']==cash[row['trader_id']] and row['escrow_balance']==0 for row in actual)
    actual_positions=data.db.query('SELECT * FROM position WHERE trader_id=ANY(%s)',(tids,))
    assert len(actual_positions)==len(positions)
    for p in actual_positions:
        q,_,pnl=positions[(p['trader_id'],p['instrument_id'])]
        assert (p['net_quantity'],p['realized_pnl'])==(q,round_minor(pnl))
    total_fee=sum(ceil_exact(f) for f in fees.values())
    assert sum(cash.values())==sum(u['initial_cash'] for u in data.users if u['trader_id'])-total_fee
    return events,{'total_assessed_fees_minor':total_fee,'accounts':[dict(r) for r in actual],
                  'positions':[{'trader_id':p['trader_id'],'instrument_id':p['instrument_id'],'net_quantity':p['net_quantity'],'gross_realized_pnl':p['realized_pnl']} for p in actual_positions]},pair_counts,pair_values


def run(seed=20261115):
    rng=random.Random(seed)
    report={'seed':seed,'transport':'in-process ASGI HTTP; real native PostgreSQL/Redis/Neo4j','crash_durable':False}
    with DemoData() as data:
        with TestClient(create_app(data.settings)) as client:
            headers=[]
            for user in data.users:
                response=client.post('/login',json={'email':user['email'],'password':user['password']})
                assert response.status_code==200
                headers.append({'Authorization':'Bearer '+response.json()['access_token']})
            admin=headers[4]; counter=itertools.count(); expected=0
            def submit(who,instrument,side,price,qty,key=None,status=201):
                body={'instrument_id':instrument['id'],'side':side,'price_ticks':price,'quantity':qty}
                request_headers=headers[who]|{'Idempotency-Key':key or f'simulation-{next(counter)}'}
                response=client.post('/orders',headers=request_headers,json=body)
                assert response.status_code==status,(response.status_code,response.text)
                return response.json()
            def cancel(who,oid):
                response=client.post(f'/orders/{oid}/cancel',headers=headers[who]);assert response.status_code==200,response.text
            def filled():
                return data.db.query('SELECT count(*) AS n FROM execution WHERE instrument_id=ANY(%s)',([i['id'] for i in data.instruments],))[0]['n']
            def cross(buyer,seller,instrument,price,qty,maker='BUY'):
                nonlocal expected
                if maker=='BUY': submit(buyer,instrument,'BUY',price,qty);submit(seller,instrument,'SELL',price,qty)
                else: submit(seller,instrument,'SELL',price,qty);submit(buyer,instrument,'BUY',price,qty)
                expected+=1;bounded(filled,lambda n:n==expected)
            a,b,c,inactive=data.instruments
            first=submit(0,a,'BUY',100,100,key='first-order')
            submit(1,a,'SELL',100,100);expected+=1;bounded(filled,lambda n:n==expected)
            assert submit(0,a,'BUY',100,100,key='first-order')==first
            cross(1,2,a,100,10);cross(2,0,a,100,10)
            partial=submit(0,a,'BUY',110,10)['order_id'];submit(1,a,'SELL',105,4);expected+=1
            cancel(0,partial);bounded(filled,lambda n:n==expected)
            jitter=rng.randrange(3)
            submit(1,b,'SELL',100+jitter,10);submit(2,b,'SELL',110+jitter,20);submit(0,b,'BUY',120+jitter,30)
            expected+=2;bounded(filled,lambda n:n==expected)
            cross(0,2,c,200,5,maker='SELL')
            submit(1,a,'SELL',99,1);rest=submit(0,a,'SELL',100,2)['order_id'];stp=submit(0,a,'BUY',101,3)['order_id'];expected+=1
            bounded(filled,lambda n:n==expected);cancel(0,rest)
            state=next(x for x in client.get('/orders/me',headers=headers[0]).json()['items'] if x['id']==stp)
            assert state['status']=='CANCELLED' and state['filled_quantity']==1
            for _ in range(10):
                buyer,seller=rng.sample(range(3),2); instrument=rng.choice((a,b,c))
                cross(buyer,seller,instrument,rng.randrange(90,150),instrument['lot_size']*rng.randrange(1,4))
            negatives={}
            for label,instrument,price,qty,status in [('bad_lot',b,100,1,422),('inactive',inactive,100,1,422),('insufficient',a,100,10**9,409),('overflow',a,2**53-1,2**63-1,422)]:
                submit(0,instrument,'BUY',price,qty,status=status);negatives[label]=status
            body={'instrument_id':a['id'],'side':'BUY','price_ticks':100,'quantity':1}
            assert client.post('/orders',json=body).status_code==401
            assert client.post('/orders',headers=admin,json=body).status_code==403
            assert client.post('/orders',headers=headers[0],json=body|{'trader_id':str(data.users[1]['trader_id'])}).status_code==422
            assert client.get('/admin/surveillance/cycles',headers=headers[0]).status_code==403
            with ThreadPoolExecutor(8) as pool:
                responses=list(pool.map(lambda i:client.post('/orders',headers=headers[3]|{'Idempotency-Key':f'race-{i}'},json=body|{'price_ticks':25000}),range(8)))
            assert sorted(r.status_code for r in responses)==[201]*3+[409]*5
            race=client.get('/account/me',headers=headers[3]).json()
            assert (race['cash_balance'],race['escrow_balance'])==(24985,75015)
            for response in responses:
                if response.status_code==201: cancel(3,response.json()['order_id'])
            bounded(filled,lambda n:n==expected)
            cycles=bounded(lambda:client.get('/admin/surveillance/cycles',headers=admin).json(),lambda r:any(set(x['trader_ids'])=={str(u['trader_id']) for u in data.users[:3]} for x in r.get('candidates',[])))
            vectors={}
            for instrument in (a,b,c):
                response=client.get(f"/admin/regimes/similar?instrument_id={instrument['id']}&current=true",headers=admin)
                assert response.status_code==200,response.text
                vectors[instrument['symbol']]=response.json()['matches'][0]
            marker='simulation'+uuid4().hex
            doc=Regimes(data.db).disclosure(a['id'],marker,'Synthetic merger and earnings disclosure')
            search=client.get('/admin/disclosures/search',headers=admin,params={'q':marker}).json()['items']
            assert search and search[0]['id']==doc
            rollup=client.get('/admin/desks/rollup',headers=admin).json()['items']
            optimizer=client.get('/admin/optimizer/compare',headers=admin,params={'instrument_id':a['id'],'lower_ticks':90,'upper_ticks':150}).json()
            assert optimizer['dataset_size']>=expected and optimizer['plans']['automatic']['Plan']
            events,financial,pair_counts,pair_values=verify_accounts(data)
            for pair,count in pair_counts.items():
                row=bounded(lambda:client.app.state.graph.run('MATCH (a:Trader {id:$a})-[r:EXECUTED_AGAINST]->(b:Trader {id:$b}) RETURN r.trade_count AS n,r.total_notional AS value',{'a':str(pair[0]),'b':str(pair[1])}),lambda r:bool(r) and r[0]['n']==count)
                assert row[0]['value']==pair_values[pair]
            e=events[0]
            replay=TradeEvent(e['id'],e['instrument_id'],e['buy_order_id'],e['sell_order_id'],e['buy_trader_id'],e['sell_trader_id'],e['price_ticks'],e['quantity'],max(e['buy_order_id'],e['sell_order_id']),e['executed_at'])
            assert data.db.settle(replay) is False
            from dataclasses import replace
            try: data.db.settle(replace(replay,quantity=replay.quantity+1))
            except UniqueViolation: pass
            else: raise AssertionError('Conflicting replay was accepted')
            client.app.state.graph.apply(replay)
            with db_connect() as conn:
                archived=conn.execute(query_text('archive'),{'cutoff':datetime.now(timezone.utc)+timedelta(seconds=1),'trader_ids':[u['trader_id'] for u in data.users if u['trader_id']]}).fetchall()
            assert archived and data.db.settle(replay) is False
            assert all(x['archived'] for x in client.get('/orders/me',headers=headers[0]).json()['items'])
            for instrument in (a,b,c):
                bounded(lambda:client.get('/market/'+instrument['symbol']+'/book',headers=headers[0]).json(),lambda r:not r.get('stale',True) and not r['bids'] and not r['asks'])
            report.update({'executions':expected,'financial':financial,'cycles':cycles['candidates'],'vectors':vectors,
                           'fts_result_id':doc,'rollup':rollup,'optimizer':optimizer,'archive_count':len(archived),
                           'race_accepted':3,'race_rejected':5,'negative_cases':negatives,
                           'same_event_replay':'no-op','conflicting_replay':'rejected','request_key_replay':'original acceptance without reservation'})
        # A cold clean restart reloads settled statistics, never rematches orders.
        with TestClient(create_app(data.settings)) as restarted:
            user=data.users[0]
            auth=restarted.post('/login',json={'email':user['email'],'password':user['password']}).json()['access_token']
            for instrument in data.instruments[:3]:
                records=[r for r in events if r['instrument_id']==instrument['id']]
                analytics=restarted.get('/market/'+instrument['symbol']+'/analytics',headers={'Authorization':'Bearer '+auth}).json()
                assert analytics['band_volume']==sum(r['quantity'] for r in records)
                window=records[-100:]
                with localcontext() as context:
                    context.prec=50
                    expected_vwap=Decimal(sum(r['price_ticks']*r['quantity'] for r in window))/Decimal(sum(r['quantity'] for r in window))
                    assert Decimal(analytics['vwap_ticks'])==expected_vwap
            report['clean_restart_analytics']='rehydrated from committed executions'
        assert data.fingerprint()==data.before
    report['scoped_cleanup']='complete';report['existing_data_preserved']=True
    return report
