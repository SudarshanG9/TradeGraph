from contextlib import contextmanager
from backend.config import Settings
from backend.stores.postgres import Database
from tests.integration.test_order_pipeline import accounts
from tests.concurrency.test_settlement_locks import reserve,make_event


def test_balances_and_positions_share_one_snapshot_across_concurrent_settlement(accounts,monkeypatch):
    users,iid=accounts;a,b=users[:2];database=Database(Settings.from_env())
    buy=reserve(a,iid,'BUY',100,1);sell=reserve(b,iid,'SELL',100,1)
    event=make_event(buy,sell,a,b,iid,100,1)
    original=database.trader_context
    settled=False
    class Interleaved:
        def __init__(self,connection):self.connection=connection
        def execute(self,statement,params=()):
            nonlocal settled
            result=self.connection.execute(statement,params)
            if statement.startswith('SELECT trader_id,cash_balance') and not settled:
                database.settle(event);settled=True
            return result
    @contextmanager
    def interleave(tid):
        with original(tid) as connection:yield Interleaved(connection)
    monkeypatch.setattr(database,'trader_context',interleave)
    snapshot=database.account_snapshot(a['trader_id'])
    assert settled and snapshot['positions']==[] and snapshot['escrow_balance']>0
    fresh=database.account_snapshot(a['trader_id'])
    assert fresh['positions'][0]['net_quantity']==1 and fresh['escrow_balance']==0
    assert fresh['cash_balance']==snapshot['cash_balance']  # reservation already removed available cash
