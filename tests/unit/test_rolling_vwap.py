from decimal import Decimal, localcontext
from random import Random
import pytest
from backend.matching.rolling_vwap import RollingVWAP


@pytest.mark.parametrize('capacity', [1, 2, 17, 100])
def test_prefix_ring_wraparound_against_history(capacity):
    ring, history, rng = RollingVWAP(capacity), [], Random(9)
    assert ring.value() is None
    for _ in range(2000):
        price, qty = rng.randrange(1, 2**63), rng.randrange(0, 100)
        history.append((price, qty))
        ring.add(price, qty)
        expected = history[-capacity:]
        value, volume = sum(p*q for p,q in expected), sum(q for p,q in expected)
        assert ring.sums() == (value, volume)
        with localcontext() as context:
            context.prec = 50
            assert ring.value() == (Decimal(value)/Decimal(volume) if volume else None)
        assert len(ring.prefixes) == capacity + 1


def test_zero_volume_and_validation():
    ring = RollingVWAP(2)
    ring.add(4, 0)
    assert ring.value() is None
    ring.add(10, 3)
    assert ring.value() == 10
    with pytest.raises(ValueError): ring.add(1.5, 2)
    with pytest.raises(ValueError): ring.add(1, -1)
