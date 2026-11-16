"""Exact executed volume with sparse Fenwick nodes over positive BIGINT ticks."""


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
    """At most 63 node updates, with no coordinate sort or full rebuild.

    A sparse dictionary stores only touched Fenwick nodes, never a dense BIGINT
    array. Memory is O(M log U), at most 63 nodes per positive-volume coordinate;
    clustered prices share most ancestors, widely sparse prices share fewer.
    """
    MAX_PRICE = 2**63 - 1

    def __init__(self):
        self.bit = {}

    def add(self, price, quantity):
        if type(price) is not int or not 0 < price <= self.MAX_PRICE:
            raise ValueError("Invalid price")
        if type(quantity) is not int or quantity < 0:
            raise ValueError("Invalid volume")
        if quantity == 0:
            return
        while price <= self.MAX_PRICE:
            self.bit[price] = self.bit.get(price, 0) + quantity
            price += price & -price

    def _prefix(self, price):
        price = min(price, self.MAX_PRICE)
        result = 0
        while price:
            result += self.bit.get(price, 0)
            price -= price & -price
        return result

    def range_sum(self, lower, upper):
        if type(lower) is not int or type(upper) is not int or lower < 0 or upper < 0:
            raise ValueError("Price bounds must be nonnegative integers")
        if lower > upper:
            return 0
        return self._prefix(upper) - self._prefix(max(0, lower - 1))
