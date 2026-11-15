"""Executed volume indexes. New coordinate rebuilds are explicitly not O(log M)."""
from bisect import bisect_left, bisect_right


class FenwickTree:
    def __init__(self, size):
        if type(size) is not int or size < 1:
            raise ValueError("Positive size required")
        self.size = size
        self.tree = [0] * (size + 1)
        self.values = [0] * size

    def point_add(self, index, delta):
        if type(index) is not int or not 0 <= index < self.size:
            raise ValueError("Index outside tree")
        if type(delta) is not int or self.values[index] + delta < 0:
            raise ValueError("Volume must remain a nonnegative integer")
        self.values[index] += delta
        index += 1
        while index <= self.size:
            self.tree[index] += delta
            index += index & -index

    def prefix_sum(self, index):
        if type(index) is not int or not -1 <= index < self.size:
            raise ValueError("Index outside tree")
        result = 0
        index += 1
        while index:
            result += self.tree[index]
            index -= index & -index
        return result

    def range_sum(self, lower, upper):
        if lower > upper:
            return 0
        return self.prefix_sum(upper) - self.prefix_sum(lower - 1)


class PriceVolumeIndex:
    """Sparse BIGINT ticks with exact coordinate expansion, O(M log M) rebuild."""
    def __init__(self):
        self.prices = []
        self.volumes = {}
        self.bit = None

    def add(self, price, quantity):
        if type(price) is not int or not 0 < price < 2**63:
            raise ValueError("Invalid price")
        if type(quantity) is not int or quantity < 0:
            raise ValueError("Invalid volume")
        new = price not in self.volumes
        self.volumes[price] = self.volumes.get(price, 0) + quantity
        if new:
            self.prices = sorted(self.volumes)
            self.bit = FenwickTree(len(self.prices))
            for index, tick in enumerate(self.prices):
                self.bit.point_add(index, self.volumes[tick])
        else:
            self.bit.point_add(bisect_left(self.prices, price), quantity)

    def range_sum(self, lower, upper):
        if lower < 0 or upper < 0:
            raise ValueError("Negative price bound")
        if lower > upper or self.bit is None:
            return 0
        left, right = bisect_left(self.prices, lower), bisect_right(self.prices, upper)
        return 0 if left == right else self.bit.range_sum(left, right - 1)
