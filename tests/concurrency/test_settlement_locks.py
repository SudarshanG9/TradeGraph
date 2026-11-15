from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timezone
import pytest
from psycopg.errors import InvalidParameterValue, UniqueViolation
from backend.config import Settings
from backend.stores.postgres import Database
from backend.events.trade_event import TradeEvent
from scripts.verify_schema import db_connect
from tests.integration.test_order_pipeline import accounts


def reserve(user, instrument, side, price, qty):
    with db_connect() as conn:
        return conn.execute('SELECT public.place_and_reserve_order(%s,%s,%s,%s,%s)',(user['trader_id'],instrument,side,price,qty)).fetchone()[0]


def make_event(buy,sell,buyer,seller,instrument,price,qty):
    with db_connect() as conn:
        eid=conn.execute("SELECT nextval('public.execution_id_seq')").fetchone()[0]
    return TradeEvent(eid,instrument,buy,sell,buyer['trader_id'],seller['trader_id'],price,qty,max(buy,sell),datetime.now(timezone.utc))


def state(user):
    with db_connect() as conn:
        return conn.execute('SELECT cash_balance,escrow_balance FROM margin_account WHERE trader_id=%s',(user['trader_id'],)).fetchone()


@pytest.mark.parametrize('partition', [[100],[1]*100,[17,3,29,1,50]])
def test_actual_sql_fee_partition_conservation_and_positions(accounts,partition):
    users,instrument=accounts
    a,b=users[:2]
    buy=reserve(a,instrument,'BUY',100,100)
    sell=reserve(b,instrument,'SELL',100,100)
    db=Database(Settings.from_env())
    for qty in partition:
        event=make_event(buy,sell,a,b,instrument,100,qty)
        assert db.settle(event)
        assert not db.settle(event)
    assert state(a)==(9999,0)
    assert state(b)==(29998,0)
    with db_connect() as conn:
        assert conn.execute('SELECT net_quantity,realized_pnl FROM position WHERE trader_id=%s AND instrument_id=%s',(a['trader_id'],instrument)).fetchone()==(100,0)
        assert conn.execute('SELECT filled_quantity,status FROM public."order" WHERE id=%s',(buy,)).fetchone()==(100,'FILLED')
        assert conn.execute('SELECT count(*) FROM execution WHERE buy_order_id=%s',(buy,)).fetchone()[0]==len(partition)


@pytest.mark.parametrize('qty,expected', [(1,((19899,0),(20099,0))),(50,((14999,0),(24999,0)))])
def test_partial_cancel_and_pooled_escrow(accounts,qty,expected):
    users,instrument=accounts
    a,b=users[:2]
    buy=reserve(a,instrument,'BUY',100,100)
    unrelated=reserve(a,instrument,'BUY',100,1)
    sell=reserve(b,instrument,'SELL',100,100)
    db=Database(Settings.from_env())
    db.settle(make_event(buy,sell,a,b,instrument,100,qty))
    assert db.cancel(unrelated,a['trader_id'])==1
    assert state(a)[1]==(100-qty)*100 + ((100-qty)*2+99)//100
    assert db.cancel(buy,a['trader_id'])==100-qty
    assert db.cancel(buy,a['trader_id'])==0
    assert db.cancel(sell,b['trader_id'])==100-qty
    assert (state(a),state(b))==expected


def test_variable_prices_mixed_maker_taker_and_seller_fee_from_proceeds(accounts):
    users,instrument=accounts
    a,b,c=users[:3]
    sell1=reserve(b,instrument,'SELL',100,50)
    buy=reserve(a,instrument,'BUY',110,100)
    db=Database(Settings.from_env())
    db.settle(make_event(buy,sell1,a,b,instrument,100,50))
    sell2=reserve(c,instrument,'SELL',105,50)
    db.settle(make_event(buy,sell2,a,c,instrument,110,50))
    assert state(a)==(9498,0)
    assert state(b)==(24999,0)
    assert state(c)==(25498,0)


def test_duplicate_conflict_and_transaction_rollback(accounts):
    users,instrument=accounts
    a,b=users[:2]
    buy=reserve(a,instrument,'BUY',100,2)
    sell=reserve(b,instrument,'SELL',100,2)
    db=Database(Settings.from_env())
    event=make_event(buy,sell,a,b,instrument,100,1)
    before=state(a),state(b)
    with db.connect() as conn:
        conn.execute('SELECT public.settle_execution(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
          (event.event_id,instrument,buy,sell,a['trader_id'],b['trader_id'],100,1,sell,event.occurred_at))
        conn.rollback()
    assert (state(a),state(b))==before
    with db_connect() as conn:
        assert conn.execute('SELECT count(*) FROM execution WHERE id=%s',(event.event_id,)).fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM position WHERE trader_id=%s',(a['trader_id'],)).fetchone()[0]==0
    assert db.settle(event)
    after=state(a),state(b)
    with pytest.raises(UniqueViolation): db.settle(replace(event,quantity=2))
    assert (state(a),state(b))==after
    with pytest.raises(InvalidParameterValue): db.settle(replace(event,event_id=event.event_id+100000000,quantity=2))
    assert (state(a),state(b))==after


def test_two_account_opposite_settlements_and_gross_pnl(accounts):
    users,instrument=accounts
    a,b=users[:2]
    buy1=reserve(a,instrument,'BUY',100,1); sell1=reserve(b,instrument,'SELL',100,1)
    buy2=reserve(b,instrument,'BUY',110,1); sell2=reserve(a,instrument,'SELL',110,1)
    events=[make_event(buy1,sell1,a,b,instrument,100,1),make_event(buy2,sell2,b,a,instrument,110,1)]
    db=Database(Settings.from_env())
    with ThreadPoolExecutor(2) as pool:
        futures=[pool.submit(db.settle,e) for e in events]
        assert all(f.result(timeout=15) for f in futures)
    assert state(a)==(20008,0) and state(b)==(19988,0)
    with db_connect() as conn:
        assert conn.execute('SELECT net_quantity,realized_pnl FROM position WHERE trader_id=%s',(a['trader_id'],)).fetchone()==(0,10)
        assert conn.execute('SELECT net_quantity,realized_pnl FROM position WHERE trader_id=%s',(b['trader_id'],)).fetchone()==(0,-10)


def test_financial_basis_guards(accounts):
    users,instrument=accounts
    reserve(users[0],instrument,'BUY',100,1)
    for query,params in [
        ('UPDATE instrument SET tick_size=tick_size+1 WHERE id=%s',(instrument,)),
        ('UPDATE margin_account SET fee_tier_id=(SELECT id FROM fee_tier WHERE tier_name=\'VIP\') WHERE trader_id=%s',(users[0]['trader_id'],)),
        ("UPDATE fee_tier SET maker_fee_bps=maker_fee_bps+1 WHERE tier_name='STANDARD'",()),
    ]:
        with db_connect() as conn:
            with pytest.raises(InvalidParameterValue):
                conn.execute(query,params)


def test_exact_weighted_average_partial_close_flip_and_short_cover(accounts):
    users,instrument=accounts
    a,b=users[:2]
    db=Database(Settings.from_env())
    steps=[('BUY',100,2),('BUY',101,1),('SELL',110,1),('SELL',90,4),('BUY',80,1),('BUY',90,1)]
    for index,(side,price,quantity) in enumerate(steps):
        first=reserve(a,instrument,side,price,quantity)
        second=reserve(b,instrument,'SELL' if side=='BUY' else 'BUY',price,quantity)
        event=make_event(first,second,a,b,instrument,price,quantity) if side=='BUY' else make_event(second,first,b,a,instrument,price,quantity)
        db.settle(event)
        if index==2:
            with db_connect() as conn:
                assert conn.execute('SELECT net_quantity,realized_pnl FROM position WHERE trader_id=%s',(a['trader_id'],)).fetchone()==(2,10)
    with db_connect() as conn:
        assert conn.execute('SELECT net_quantity,realized_pnl FROM position WHERE trader_id=%s',(a['trader_id'],)).fetchone()==(0,-1)
    assert state(a)==(19993,0) and state(b)==(19995,0)


@pytest.mark.parametrize('accounts',['VIP'],indirect=True)
def test_vip_fractional_fee_partitioning(accounts):
    users,instrument=accounts
    a,b=users[:2]
    buy=reserve(a,instrument,'BUY',100,100)
    sell=reserve(b,instrument,'SELL',100,100)
    db=Database(Settings.from_env())
    for _ in range(100): db.settle(make_event(buy,sell,a,b,instrument,100,1))
    assert state(a)==(9999,0) and state(b)==(29999,0)


def test_concurrent_duplicate_event_has_one_financial_effect(accounts):
    users,instrument=accounts
    a,b=users[:2]
    buy=reserve(a,instrument,'BUY',100,1); sell=reserve(b,instrument,'SELL',100,1)
    event=make_event(buy,sell,a,b,instrument,100,1)
    db=Database(Settings.from_env())
    with ThreadPoolExecutor(2) as pool:
        assert sorted([f.result(timeout=15) for f in [pool.submit(db.settle,event),pool.submit(db.settle,event)]])==[False,True]
    assert state(a)==(19899,0) and state(b)==(20099,0)


def test_settlement_overflow_rolls_back_execution_accounts_and_trigger(accounts):
    from psycopg.errors import NumericValueOutOfRange
    users,instrument=accounts
    a,b=users[:2]
    maximum=2**63-1
    with db_connect() as conn:
        conn.execute('UPDATE margin_account SET cash_balance=%s WHERE trader_id=ANY(%s)',(maximum,[a['trader_id'],b['trader_id']]))
    price=maximum//4
    buy=reserve(a,instrument,'BUY',price,1); sell=reserve(b,instrument,'SELL',100,1)
    event=make_event(buy,sell,a,b,instrument,price,1)
    before=state(a),state(b)
    with pytest.raises(NumericValueOutOfRange): Database(Settings.from_env()).settle(event)
    assert (state(a),state(b))==before
    with db_connect() as conn:
        assert conn.execute('SELECT count(*) FROM execution WHERE id=%s',(event.event_id,)).fetchone()[0]==0
        assert conn.execute('SELECT count(*) FROM position WHERE trader_id=ANY(%s)',([a['trader_id'],b['trader_id']],)).fetchone()[0]==0
        assert conn.execute('SELECT filled_quantity FROM public."order" WHERE id=%s',(buy,)).fetchone()[0]==0
