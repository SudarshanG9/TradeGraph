from collections import defaultdict
from dataclasses import dataclass
from heapq import heappop, heappush


@dataclass(frozen=True, slots=True)
class Order:
    order_id: int
    trader_id: str
    instrument_id: int
    side: str
    price_ticks: int
    quantity: int


@dataclass(frozen=True, slots=True)
class Fill:
    instrument_id: int
    buy_order_id: int
    sell_order_id: int
    buy_trader_id: str
    sell_trader_id: str
    price_ticks: int
    quantity: int


@dataclass(frozen=True, slots=True)
class MatchResult:
    fills: tuple[Fill, ...]
    remaining: int
    resting: bool
    self_trade_prevented: bool


class _Node:
    __slots__ = ("order", "remaining", "prev", "next")

    def __init__(self, order: Order, remaining: int):
        self.order = order
        self.remaining = remaining
        self.prev = None
        self.next = None


class _PriceLevel:
    __slots__ = ("head", "tail", "total_quantity")

    def __init__(self):
        self.head = None
        self.tail = None
        self.total_quantity = 0

    def append(self, node: _Node) -> None:
        node.prev = self.tail
        node.next = None
        if self.tail is None:
            self.head = node
        else:
            self.tail.next = node
        self.tail = node
        self.total_quantity += node.remaining

    def remove(self, node: _Node) -> None:
        if node.prev is None:
            self.head = node.next
        else:
            node.prev.next = node.next
        if node.next is None:
            self.tail = node.prev
        else:
            node.next.prev = node.prev
        self.total_quantity -= node.remaining
        node.prev = None
        node.next = None


class OrderBook:
    """Single-writer, memory-only, price-time limit-order book."""

    def __init__(self):
        # (instrument_id, side, price_ticks) -> linked FIFO price level
        self._levels = {}
        # (instrument_id, side) -> min heap (negative for bids)
        self._heaps = defaultdict(list)
        # (instrument_id, side) -> prices already represented in heap
        self._queued_prices = defaultdict(set)
        # order_id -> (level_key, intrusive node)
        self._by_id = {}
        self._seen_ids = set()

    @staticmethod
    def _validate(order: Order) -> None:
        if type(order.order_id) is not int or not (0 < order.order_id < 2**63):
            raise ValueError("Invalid order ID")
        if type(order.instrument_id) is not int or order.instrument_id <= 0:
            raise ValueError("Invalid instrument ID")
        if not isinstance(order.trader_id, str) or not order.trader_id:
            raise ValueError("Invalid trader ID")
        if order.side not in ("BUY", "SELL"):
            raise ValueError("Invalid side")
        if type(order.price_ticks) is not int or not (0 < order.price_ticks < 2**63):
            raise ValueError("Invalid price ticks")
        if type(order.quantity) is not int or not (0 < order.quantity < 2**63):
            raise ValueError("Invalid quantity")

    def _best_price(self, instrument_id: int, side: str):
        book_key = (instrument_id, side)
        heap = self._heaps[book_key]
        queued = self._queued_prices[book_key]
        while heap:
            price = -heap[0] if side == "BUY" else heap[0]
            if (instrument_id, side, price) in self._levels:
                return price
            heappop(heap)
            queued.discard(price)
        return None

    def _insert_resting(self, order: Order, remaining: int):
        key = (order.instrument_id, order.side, order.price_ticks)
        level = self._levels.get(key)
        if level is None:
            level = _PriceLevel()
            self._levels[key] = level
            heap_key = (order.instrument_id, order.side)
            if order.price_ticks not in self._queued_prices[heap_key]:
                heap_price = -order.price_ticks if order.side == "BUY" else order.price_ticks
                heappush(self._heaps[heap_key], heap_price)
                self._queued_prices[heap_key].add(order.price_ticks)
        node = _Node(order, remaining)
        level.append(node)
        self._by_id[order.order_id] = (key, node)

    def submit(self, order: Order) -> MatchResult:
        self._validate(order)
        if order.order_id in self._seen_ids:
            raise ValueError("Duplicate order ID")
        self._seen_ids.add(order.order_id)

        remaining = order.quantity
        fills = []
        prevented = False
        opposite = "SELL" if order.side == "BUY" else "BUY"

        while remaining > 0:
            best = self._best_price(order.instrument_id, opposite)
            if best is None:
                break
            crosses = (order.price_ticks >= best if order.side == "BUY"
                       else order.price_ticks <= best)
            if not crosses:
                break
            key = (order.instrument_id, opposite, best)
            level = self._levels[key]
            maker = level.head
            if maker is None:
                raise AssertionError("Active level cannot have an empty FIFO queue")
            if maker.order.trader_id == order.trader_id:
                # Explicit Day 2 STP policy: cancel the incoming residual.
                prevented = True
                break

            qty = min(remaining, maker.remaining)
            buyer = order if order.side == "BUY" else maker.order
            seller = maker.order if order.side == "BUY" else order
            fills.append(Fill(
                instrument_id=order.instrument_id,
                buy_order_id=buyer.order_id,
                sell_order_id=seller.order_id,
                buy_trader_id=buyer.trader_id,
                sell_trader_id=seller.trader_id,
                price_ticks=maker.order.price_ticks,
                quantity=qty,
            ))
            remaining -= qty
            maker.remaining -= qty
            level.total_quantity -= qty
            if maker.remaining == 0:
                level.remove(maker)  # remaining == 0, so no double decrement
                del self._by_id[maker.order.order_id]
                if level.head is None:
                    del self._levels[key]  # heap entry cleaned lazily

        resting = remaining > 0 and not prevented
        if resting:
            self._insert_resting(order, remaining)
        return MatchResult(tuple(fills), remaining, resting, prevented)

    def cancel(self, order_id: int) -> int:
        """Remove one resting order in O(1) and return unfilled quantity."""
        found = self._by_id.pop(order_id, None)
        if found is None:
            return 0
        key, node = found
        level = self._levels[key]
        cancelled_qty = node.remaining
        level.remove(node)
        if level.head is None:
            del self._levels[key]
        return cancelled_qty

    def depth(self, instrument_id: int, side: str):
        """Sorted snapshot: (price_ticks, aggregate resting quantity)."""
        if side not in ("BUY", "SELL"):
            raise ValueError("Invalid side")
        snapshot = [
            (price, level.total_quantity)
            for (inst, s, price), level in self._levels.items()
            if inst == instrument_id and s == side
        ]
        return sorted(snapshot, key=lambda p: p[0], reverse=(side == "BUY"))

    def assert_internal_invariants(self):
        """Slow diagnostic; never call this on a production hot path."""
        observed_ids = set()
        for key, level in self._levels.items():
            assert level.head is not None and level.tail is not None
            assert level.head.prev is None and level.tail.next is None
            total = 0
            prev = None
            node = level.head
            while node is not None:
                assert node.prev is prev
                assert node.remaining > 0
                assert (node.order.instrument_id, node.order.side,
                        node.order.price_ticks) == key
                assert self._by_id[node.order.order_id] == (key, node)
                assert node.order.order_id not in observed_ids
                observed_ids.add(node.order.order_id)
                total += node.remaining
                prev, node = node, node.next
            assert prev is level.tail
            assert total == level.total_quantity and total > 0
        assert observed_ids == set(self._by_id)
