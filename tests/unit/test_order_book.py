from concurrent.futures import ThreadPoolExecutor
import pytest
from backend.matching.engine import Engine
from backend.matching.order_book import Order
from tests.unit.test_matching import event


def test_engine_owner_and_settled_analytics_idempotency():
    engine = Engine(2)
    engine.submit(Order(1, 'alice', 1, 'BUY', 100, 3))
    assert engine.volume[1].range_sum(0, 1000) == 0
    with ThreadPoolExecutor(1) as pool:
        with pytest.raises(RuntimeError):
            pool.submit(engine.cancel, 1).result()
    assert engine.cancel(1) == 3
    assert engine.apply_settled(event())
    assert not engine.apply_settled(event())
    assert engine.volume[1].range_sum(100, 100) == 100
    assert engine.vwap[1].value() == 100


def test_monotonic_owner_identity_stays_constant_after_fills_and_cancels():
    engine=Engine(monotonic_order_ids=True)
    for oid in range(1,10001):
        engine.submit(Order(oid,'alice',1,'BUY',100,1));engine.cancel(oid)
    assert engine.book._seen_ids is None and engine.book._last_id==10000
    for oid in (1,5000,10000):
        with pytest.raises(ValueError,match='Duplicate'): engine.submit(Order(oid,'alice',1,'BUY',100,1))
    engine.submit(Order(10001,'bob',1,'SELL',100,1))
    engine.submit(Order(10002,'alice',1,'BUY',100,1))
    with pytest.raises(ValueError,match='Duplicate'): engine.submit(Order(10001,'bob',1,'SELL',100,1))
    # Standalone public mode retains arbitrary arrival IDs and exact duplicates.
    direct=Engine();direct.submit(Order(20,'a',1,'BUY',100,1));direct.submit(Order(10,'a',1,'BUY',100,1))


def test_exact_compact_execution_identity_rejects_conflicts_after_long_history():
    from dataclasses import replace
    from datetime import timedelta
    engine=Engine()
    original=event()
    for i in range(10001): engine.apply_settled(replace(original,event_id=i+1))
    replay=replace(original,event_id=1)
    assert not engine.apply_settled(replay)
    for change in ({'quantity':101},{'occurred_at':original.occurred_at+timedelta(microseconds=1)}, {'price_ticks':101}):
        with pytest.raises(ValueError,match='Conflicting'): engine.apply_settled(replace(replay,**change))
    assert len(engine.settled[1])==84
    assert engine.volume[1].range_sum(0,1000)==10001*100
