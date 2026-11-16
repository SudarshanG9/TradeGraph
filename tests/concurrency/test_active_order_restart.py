"""Unproven active financial state must preserve data and refuse cold startup."""
import os
import pytest
from backend.config import Settings
from backend.stores.postgres import Database
from tests.integration.test_order_pipeline import accounts
from tests.concurrency.test_settlement_locks import reserve, make_event


@pytest.fixture(autouse=True)
def isolated_only():
    if not os.environ.get('POSTGRES_DB','').startswith('tradegraph_test_'):
        pytest.skip('Requires explicit isolated test database')


@pytest.mark.parametrize('side',['BUY','SELL'])
def test_resting_reservation_refused_without_changing_escrow(accounts,side):
    users,iid=accounts
    reserve(users[0],iid,side,100,2)
    db=Database(Settings.from_env())
    before=db.query('SELECT cash_balance,escrow_balance FROM margin_account WHERE trader_id=%s',(users[0]['trader_id'],))
    for _ in range(2):
        with pytest.raises(RuntimeError,match='Unresolved active orders'):
            db.acquire_owner()
    assert db.query('SELECT cash_balance,escrow_balance FROM margin_account WHERE trader_id=%s',(users[0]['trader_id'],))==before
    assert before[0]['escrow_balance']==201


def test_partial_commit_pending_remainder_refused_without_duplicate_fill(accounts):
    users,iid=accounts;a,b=users[:2]
    buy=reserve(a,iid,'BUY',100,2);sell=reserve(b,iid,'SELL',100,1)
    event=make_event(buy,sell,a,b,iid,100,1)
    db=Database(Settings.from_env());db.settle(event)
    before=db.query('SELECT * FROM margin_account WHERE trader_id=ANY(%s)',([a['trader_id'],b['trader_id']],))
    with pytest.raises(RuntimeError,match='operator reconciliation'):
        db.acquire_owner()
    assert not db.settle(event)
    assert db.query('SELECT * FROM margin_account WHERE trader_id=ANY(%s)',([a['trader_id'],b['trader_id']],))==before
    assert db.query('SELECT filled_quantity,status FROM public."order" WHERE id=%s',(buy,))==[{'filled_quantity':1,'status':'PARTIAL'}]
