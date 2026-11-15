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
