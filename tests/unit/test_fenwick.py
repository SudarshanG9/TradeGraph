from random import Random
import pytest
from backend.matching.fenwick import FenwickTree, PriceVolumeIndex


def test_bit_against_scan_with_boundaries_and_large_values():
    rng = Random(22)
    bit = FenwickTree(257)
    values = [0] * 257
    for _ in range(2000):
        index, delta = rng.randrange(257), rng.randrange(2**63)
        values[index] += delta
        bit.point_add(index, delta)
        lo, hi = sorted([rng.randrange(257), rng.randrange(257)])
        assert bit.range_sum(lo, hi) == sum(values[lo:hi+1])
    assert bit.prefix_sum(-1) == 0
    assert bit.prefix_sum(256) == sum(values)
    assert bit.range_sum(10, 9) == 0
    with pytest.raises(ValueError): bit.point_add(0, -values[0] - 1)
    with pytest.raises(ValueError): bit.point_add(257, 1)


def test_dynamic_coordinates_and_instrument_separation():
    first, second = PriceVolumeIndex(), PriceVolumeIndex()
    assert first.range_sum(0, 100) == 0
    for price in (100, 2**63-1, 1, 101, 100): first.add(price, 7)
    second.add(100, 99)
    assert first.range_sum(100, 101) == 21
    assert first.range_sum(0, 2**63-1) == 35
    assert second.range_sum(0, 101) == 99
    assert first.range_sum(102, 200) == 0
    with pytest.raises(ValueError): first.add(-1, 4)
    with pytest.raises(ValueError): first.add(1, -1)
