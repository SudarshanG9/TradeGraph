"""Native archival proof on uniquely owned rows, without a matching owner."""
from datetime import datetime, timedelta, timezone
from psycopg.errors import UniqueViolation
import pytest
from backend.config import Settings
from backend.stores.postgres import Database, query_text
from scripts.verify_schema import db_connect
from tests.integration.test_order_pipeline import accounts
from tests.concurrency.test_settlement_locks import reserve, make_event


def params(users):
    return {'cutoff':datetime.now(timezone.utc)+timedelta(days=1),
            'trader_ids':[u['trader_id'] for u in users]}


def test_archive_excludes_partial_and_preserves_execution_after_cancel(accounts):
    users,instrument=accounts; a,b=users[:2]
    buy=reserve(a,instrument,'BUY',100,2); sell=reserve(b,instrument,'SELL',100,2)
    event=make_event(buy,sell,a,b,instrument,100,1)
    db=Database(Settings.from_env()); db.settle(event)
    with db_connect() as conn:
        assert not conn.execute(query_text('archive'),params([a,b])).fetchall()
    db.cancel(buy,a['trader_id'])
    with db_connect() as conn:
        moved=conn.execute(query_text('archive'),params([a,b])).fetchall()
        assert len(moved)==1 and moved[0][0]==buy
        assert conn.execute('SELECT count(*) FROM execution WHERE id=%s',(event.event_id,)).fetchone()==(1,)
        assert conn.execute('SELECT status,filled_quantity FROM public."order" WHERE id=%s',(sell,)).fetchone()==('PARTIAL',1)
        assert not conn.execute(query_text('archive'),params([a,b])).fetchall()


def test_archive_insert_failure_rolls_back_delete(accounts):
    users,instrument=accounts; a=users[0]
    buy=reserve(a,instrument,'BUY',100,1)
    Database(Settings.from_env()).cancel(buy,a['trader_id'])
    with db_connect() as conn:
        conn.execute('''INSERT INTO order_history(id,trader_id,instrument_id,side,price_ticks,quantity,filled_quantity,status,created_at,updated_at)
          SELECT id,trader_id,instrument_id,side,price_ticks,quantity,filled_quantity,status,created_at,updated_at FROM public."order" WHERE id=%s''',(buy,))
    with db_connect() as conn:
        with pytest.raises(UniqueViolation): conn.execute(query_text('archive'),params([a]))
    with db_connect() as conn:
        assert conn.execute('SELECT status FROM public."order" WHERE id=%s',(buy,)).fetchone()==('CANCELLED',)
        assert conn.execute('SELECT count(*) FROM order_history WHERE id=%s',(buy,)).fetchone()==(1,)


def test_archive_during_uncommitted_settlement_waits_for_eligibility(accounts):
    users,instrument=accounts; a,b=users[:2]
    buy=reserve(a,instrument,'BUY',100,1); sell=reserve(b,instrument,'SELL',100,1)
    e=make_event(buy,sell,a,b,instrument,100,1)
    db=Database(Settings.from_env())
    with db.connect() as settling:
        settling.execute("SET LOCAL app.role='TRADER'")
        settling.execute('SELECT public.settle_execution(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (e.event_id,e.instrument_id,e.buy_order_id,e.sell_order_id,e.buy_trader_id,e.sell_trader_id,e.price_ticks,e.quantity,e.taker_order_id,e.occurred_at))
        with db_connect() as archiving:
            archiving.execute("SET LOCAL statement_timeout='1s'")
            assert not archiving.execute(query_text('archive'),params([a,b])).fetchall()
    with db_connect() as conn:
        assert len(conn.execute(query_text('archive'),params([a,b])).fetchall())==2
        assert conn.execute('SELECT count(*) FROM execution WHERE id=%s',(e.event_id,)).fetchone()==(1,)


def test_archive_requires_execution_volume_reconciliation(accounts):
    users,instrument=accounts; a=users[0]
    buy=reserve(a,instrument,'BUY',100,1)
    with db_connect() as conn:
        # Deliberately inconsistent fixture state remains uncommitted and rolls back.
        conn.execute('UPDATE public."order" SET status=\'FILLED\',filled_quantity=1 WHERE id=%s',(buy,))
        assert not conn.execute(query_text('archive'),params([a])).fetchall()
        assert conn.execute('SELECT id FROM public."order" WHERE id=%s',(buy,)).fetchone()==(buy,)
        conn.rollback()


def test_bounded_archive_skips_locked_rows_and_is_idempotent(accounts):
    users,instrument=accounts;a=users[0];db=Database(Settings.from_env())
    ids=[reserve(a,instrument,'BUY',100,1) for _ in range(4)]
    for oid in ids: db.cancel(oid,a['trader_id'])
    cutoff=params([a])['cutoff']
    with db_connect() as locker:
        locker.execute('SELECT id FROM public."order" WHERE id=%s FOR UPDATE',(ids[0],))
        moved=db.archive_terminal_orders(cutoff,2,[a['trader_id']])
        assert len(moved)==2 and ids[0] not in {r['id'] for r in moved}
    assert len(db.archive_terminal_orders(cutoff,2,[a['trader_id']]))==2
    assert db.archive_terminal_orders(cutoff,2,[a['trader_id']])==[]
