"""Fault injection around real isolated PostgreSQL transactions; no API owner."""
import asyncio
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
import psycopg
import pytest
from backend.config import Settings
from backend.stores.postgres import Database
from backend.workers.settlement_worker import SettlementWorker
from backend.events.dispatcher import Dispatcher
from tests.integration.test_order_pipeline import accounts
from tests.concurrency.test_settlement_locks import reserve, make_event, state
from scripts.verify_schema import db_connect


def fixture_event(accounts):
    users, instrument = accounts
    a,b = users[:2]
    buy=reserve(a,instrument,'BUY',100,1)
    sell=reserve(b,instrument,'SELL',100,1)
    return a,b,make_event(buy,sell,a,b,instrument,100,1)


def drive(db,event,callbacks=()):
    async def run():
        dispatcher=Dispatcher(8)
        observed=[]
        worker=SettlementWorker(db,SimpleNamespace(apply_settled=observed.append),dispatcher)
        worker.after_commit=list(callbacks)
        dispatcher.publish([event])
        worker.start()
        try:
            try: await worker.drain()
            except RuntimeError: pass
            return worker,dispatcher,observed
        finally: await worker.stop()
    return asyncio.run(run())


def assert_committed(a,b,event):
    assert state(a)==(19899,0) and state(b)==(20099,0)
    with db_connect() as conn:
        assert conn.execute('SELECT count(*) FROM execution WHERE id=%s',(event.event_id,)).fetchone()==(1,)
        assert conn.execute('SELECT filled_quantity,status FROM public."order" WHERE id=ANY(%s) ORDER BY id',([event.buy_order_id,event.sell_order_id],)).fetchall()==[(1,'FILLED'),(1,'FILLED')]
        for user,qty in ((a,1),(b,-1)):
            assert conn.execute('SELECT net_quantity,realized_pnl FROM position WHERE trader_id=%s AND instrument_id=%s',(user['trader_id'],event.instrument_id)).fetchone()==(qty,0)


@pytest.mark.parametrize('error',[psycopg.errors.SerializationFailure,psycopg.errors.DeadlockDetected,psycopg.errors.QueryCanceled,psycopg.errors.LockNotAvailable])
def test_aborted_transaction_retries_same_event(accounts,error):
    a,b,event=fixture_event(accounts)
    db=Database(Settings.from_env()); original=db.settle; calls=[]
    def injected(e):
        calls.append(e)
        if len(calls)==1:
            # Real financial work including trigger, then injected transaction abort.
            # Connection context must roll back ALL effects before retry.
            with db.connect() as conn:
                conn.execute("SET LOCAL app.role='TRADER'")
                conn.execute('SELECT public.settle_execution(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                    (e.event_id,e.instrument_id,e.buy_order_id,e.sell_order_id,e.buy_trader_id,e.sell_trader_id,e.price_ticks,e.quantity,e.taker_order_id,e.occurred_at))
                raise error('injected rollback')
        assert state(a)==(19899,101) and state(b)==(19899,101)
        return original(e)
    db.settle=injected
    worker,dispatcher,observed=drive(db,event)
    assert len(calls)==2 and all(e is event for e in calls)
    assert observed==[event] and worker.pending is None and dispatcher.failure is None
    assert_committed(a,b,event)


@pytest.mark.parametrize('outcome',['committed','absent','conflicting'])
def test_uncertain_connection_outcome_reconciles_without_blind_retry(accounts,outcome):
    a,b,event=fixture_event(accounts)
    db=Database(Settings.from_env()); original=db.settle; calls=[]
    def lost_ack(e):
        calls.append(e)
        if outcome!='absent':
            original(e if outcome=='committed' else replace(e,occurred_at=e.occurred_at+timedelta(seconds=1)))
        raise psycopg.OperationalError('lost acknowledgement')
    db.settle=lost_ack
    worker,dispatcher,observed=drive(db,event)
    assert len(calls)==1
    if outcome=='committed':
        assert not dispatcher.failure and observed==[event] and worker.pending is None
        assert_committed(a,b,event)
    else:
        assert dispatcher.failure and worker.pending is event and observed==[]
        if outcome=='absent':
            assert state(a)==(19899,101) and state(b)==(19899,101)
            with db_connect() as conn:
                assert conn.execute('SELECT count(*) FROM execution WHERE id=%s',(event.event_id,)).fetchone()==(0,)
        else: assert_committed(a,b,event)


def test_retry_exhaustion_retains_immutable_pending_event(accounts):
    a,b,event=fixture_event(accounts)
    db=Database(Settings.from_env()); calls=[]
    def timeout(e):
        calls.append(e)
        raise psycopg.errors.QueryCanceled('injected timeout')
    db.settle=timeout
    worker,dispatcher,observed=drive(db,event)
    assert calls==[event]*3 and worker.pending is event and dispatcher.failure
    assert not observed and state(a)==(19899,101) and state(b)==(19899,101)

@pytest.mark.parametrize('kind',['statement','lock'])
def test_real_postgres_timeout_rolls_back_then_recovers(accounts,kind):
    a,b,event=fixture_event(accounts)
    db=Database(Settings.from_env()); original=db.settle; calls=[]; codes=[]
    def timeout_once(e):
        calls.append(e)
        if len(calls)>1: return original(e)
        with db_connect() as locker:
            if kind=='lock':
                locker.execute('SELECT trader_id FROM margin_account WHERE trader_id=%s FOR UPDATE',(a['trader_id'],))
            try:
                with db.connect() as conn:
                    conn.execute("SET LOCAL app.role='TRADER'")
                    if kind=='statement':
                        conn.execute("SET LOCAL statement_timeout='5ms'")
                        conn.execute('SELECT pg_sleep(0.1)')
                    else:
                        conn.execute("SET LOCAL lock_timeout='5ms'")
                        conn.execute('SELECT public.settle_execution(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                            (e.event_id,e.instrument_id,e.buy_order_id,e.sell_order_id,e.buy_trader_id,e.sell_trader_id,e.price_ticks,e.quantity,e.taker_order_id,e.occurred_at))
            except psycopg.Error as exc:
                codes.append(exc.sqlstate)
                raise
    db.settle=timeout_once
    worker,dispatcher,observed=drive(db,event)
    assert codes==['57014' if kind=='statement' else '55P03']
    assert len(calls)==2 and observed==[event] and not dispatcher.failure
    assert_committed(a,b,event)
