"""Last-N-fill VWAP from cumulative prefixes in a circular N+1-slot array."""
from decimal import Decimal, localcontext


class RollingVWAP:
    def __init__(self, capacity=100):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("Positive capacity required")
        self.capacity = capacity
        self.prefixes = [(0, 0)] * (capacity + 1)
        self.count = 0
        self.total_value = self.total_volume = 0

    def add(self, price_ticks, quantity):
        if type(price_ticks) is not int or price_ticks <= 0:
            raise ValueError("Invalid integer price")
        if type(quantity) is not int or quantity < 0:
            raise ValueError("Invalid integer quantity")
        self.total_value += price_ticks * quantity
        self.total_volume += quantity
        self.count += 1
        self.prefixes[self.count % len(self.prefixes)] = (self.total_value, self.total_volume)

    def sums(self):
        baseline = max(0, self.count - self.capacity)
        value, volume = self.prefixes[baseline % len(self.prefixes)]
        return self.total_value - value, self.total_volume - volume

    def value(self):
        value, volume = self.sums()
        if not volume:
            return None
        with localcontext() as context:
            context.prec = 50
            return Decimal(value) / Decimal(volume)
