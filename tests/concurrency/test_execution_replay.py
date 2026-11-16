from backend.config import Settings
from backend.stores.postgres import Database
from tests.integration.test_order_pipeline import accounts
from tests.concurrency.test_settlement_locks import reserve, make_event
from backend.events.trade_event import TradeEvent
from backend.matching.engine import Engine
import pytest


def test_replay_batches_snapshot_order_and_exact_analytics(accounts):
    users,instrument=accounts;a,b=users[:2];db=Database(Settings.from_env())
    buy=reserve(a,instrument,'BUY',100,8);sell=reserve(b,instrument,'SELL',100,8)
    events=[make_event(buy,sell,a,b,instrument,100,1) for _ in range(8)]
    for event in events[:7]: db.settle(event)
    batches=db.execution_batches(2)
    first=next(batches)
    db.settle(events[-1])  # after the repeatable-read cursor snapshot
    rows=first+[r for batch in batches for r in batch]
    assert [r['id'] for r in rows]==sorted(r['id'] for r in rows)
    own=[r for r in rows if r['instrument_id']==instrument]
    assert len(own)==7 and events[-1].event_id not in {r['id'] for r in rows}
    engine=Engine()
    for r in own:
        event=TradeEvent(r['id'],r['instrument_id'],r['buy_order_id'],r['sell_order_id'],r['buy_trader_id'],r['sell_trader_id'],r['price_ticks'],r['quantity'],max(r['buy_order_id'],r['sell_order_id']),r['executed_at'])
        assert engine.apply_settled(event)
        assert not engine.apply_settled(event)
    assert engine.volume[instrument].range_sum(0,2**63-1)==7
    assert str(engine.vwap[instrument].value())=='100'
    for invalid in (0,True,10001):
        with pytest.raises(ValueError): next(db.execution_batches(invalid))
    interrupted=db.execution_batches(1);next(interrupted);interrupted.close()


def test_restart_diagnostic_counts_only_this_database_owner(accounts):
    from scripts.reconcile_restart import diagnose
    db=Database(Settings.from_env());lease=db.acquire_owner()
    try:
        result=diagnose(db)
        assert result['matching_owner_locks']==1 and not result['cold_start_safe']
    finally:lease.close()
    assert diagnose(db)['matching_owner_locks']==0
