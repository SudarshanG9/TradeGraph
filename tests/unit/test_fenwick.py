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


@pytest.mark.parametrize('mode',['dense','sparse','increasing','decreasing'])
def test_sparse_fenwick_randomized_reference(mode):
    rng=Random(20261116);index=PriceVolumeIndex();reference={}
    prices=(list(range(1,3001)) if mode!='sparse' else [rng.randrange(1,2**63) for _ in range(3000)])
    if mode=='decreasing': prices.reverse()
    if mode=='dense': rng.shuffle(prices)
    for price in prices:
        quantity=rng.randrange(10**20)
        index.add(price,quantity);reference[price]=reference.get(price,0)+quantity
        if rng.random()<0.05:
            low,high=sorted((rng.randrange(2**63),rng.randrange(2**63))) if mode=='sparse' else sorted((rng.randrange(3100),rng.randrange(3100)))
            assert index.range_sum(low,high)==sum(q for p,q in reference.items() if low<=p<=high)
    assert index.range_sum(0,2**63+100)==sum(reference.values())
    assert index.range_sum(2**63,2**64)==0
    assert index.range_sum(2,1)==0
    assert len(index.bit)<=63*len(reference)
    before=dict(index.bit);index.add(2**63-1,0);assert index.bit==before
    for value in (True,1.5,'1',-1):
        with pytest.raises(ValueError):index.range_sum(value,10)
        with pytest.raises(ValueError):index.add(value,1)
