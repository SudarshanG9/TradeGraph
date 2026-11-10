from random import Random

import pytest

from backend.matching.order_book import Fill, MatchResult, Order, OrderBook

pytestmark = pytest.mark.day2


class ReferenceBook:
    """Intentionally slow scan-based correctness oracle."""

    def __init__(self):
        self.active = []  # [order, remainder], in arrival order
        self.seen = set()

    def submit(self, order):
        if order.order_id in self.seen:
            raise ValueError("Duplicate order ID")
        self.seen.add(order.order_id)
        remainder = order.quantity
        fills = []
        prevented = False
        while remainder:
            candidates = []
            for arrival, (maker, _) in enumerate(self.active):
                if maker.instrument_id != order.instrument_id or maker.side == order.side:
                    continue
                eligible = (maker.price_ticks <= order.price_ticks
                            if order.side == "BUY" else maker.price_ticks >= order.price_ticks)
                if eligible:
                    priority = maker.price_ticks if order.side == "BUY" else -maker.price_ticks
                    candidates.append((priority, arrival))
            if not candidates:
                break
            _, maker_index = min(candidates)
            maker, maker_qty = self.active[maker_index]
            if maker.trader_id == order.trader_id:
                prevented = True
                break
            qty = min(remainder, maker_qty)
            buyer = order if order.side == "BUY" else maker
            seller = maker if order.side == "BUY" else order
            fills.append(Fill(
                order.instrument_id, buyer.order_id, seller.order_id,
                buyer.trader_id, seller.trader_id,
                maker.price_ticks, qty,
            ))
            remainder -= qty
            self.active[maker_index][1] -= qty
            if self.active[maker_index][1] == 0:
                del self.active[maker_index]
        resting = remainder > 0 and not prevented
        if resting:
            self.active.append([order, remainder])
        return MatchResult(tuple(fills), remainder, resting, prevented)

    def cancel(self, order_id):
        for index, (order, remainder) in enumerate(self.active):
            if order.order_id == order_id:
                del self.active[index]
                return remainder
        return 0

    def depth(self, instrument_id, side):
        grouped = {}
        for order, quantity in self.active:
            if order.instrument_id == instrument_id and order.side == side:
                grouped[order.price_ticks] = grouped.get(order.price_ticks, 0) + quantity
        return sorted(grouped.items(), reverse=(side == "BUY"))


def test_price_priority_and_resting_execution_price():
    book = OrderBook()
    book.submit(Order(1, "alice", 1, "SELL", 103, 2))
    book.submit(Order(2, "bob", 1, "SELL", 101, 2))
    result = book.submit(Order(3, "carol", 1, "BUY", 105, 3))
    assert [(x.sell_order_id, x.price_ticks, x.quantity) for x in result.fills] == [
        (2, 101, 2), (1, 103, 1)
    ]
    assert book.depth(1, "SELL") == [(103, 1)]
    book.assert_internal_invariants()


def test_fifo_at_same_price_partial_fill_then_cancel():
    book = OrderBook()
    book.submit(Order(1, "alice", 1, "SELL", 101, 5))
    book.submit(Order(2, "bob", 1, "SELL", 101, 8))
    result = book.submit(Order(3, "carol", 1, "BUY", 105, 10))
    assert [(x.sell_order_id, x.quantity) for x in result.fills] == [(1, 5), (2, 5)]
    assert book.depth(1, "SELL") == [(101, 3)]
    assert book.cancel(2) == 3
    assert book.cancel(2) == 0
    assert book.depth(1, "SELL") == []
    book.assert_internal_invariants()


def test_non_crossing_and_instrument_isolation():
    book = OrderBook()
    book.submit(Order(1, "alice", 1, "SELL", 120, 5))
    book.submit(Order(2, "bob", 2, "BUY", 130, 5))
    result = book.submit(Order(3, "carol", 1, "BUY", 100, 5))
    assert result.fills == ()
    assert book.depth(1, "SELL") == [(120, 5)]
    assert book.depth(1, "BUY") == [(100, 5)]
    assert book.depth(2, "BUY") == [(130, 5)]


def test_self_trade_prevention():
    book = OrderBook()
    book.submit(Order(1, "alice", 1, "SELL", 100, 2))
    result = book.submit(Order(2, "alice", 1, "BUY", 105, 2))
    assert result.self_trade_prevented
    assert result.remaining == 2 and not result.resting
    assert not result.fills
    assert book.depth(1, "SELL") == [(100, 2)]
    assert book.depth(1, "BUY") == []


def test_self_trade_prevention_keeps_prior_fills_and_fifo():
    book = OrderBook()
    book.submit(Order(1, "bob", 1, "SELL", 99, 1))
    book.submit(Order(2, "alice", 1, "SELL", 100, 2))
    book.submit(Order(3, "carol", 1, "SELL", 100, 3))

    result = book.submit(Order(4, "alice", 1, "BUY", 101, 4))

    assert result == MatchResult((Fill(1, 4, 1, "alice", "bob", 99, 1),), 3, False, True)
    assert book.depth(1, "SELL") == [(100, 5)]
    assert book.depth(1, "BUY") == []
    book.assert_internal_invariants()


def test_price_level_removal_and_recreation():
    book = OrderBook()
    book.submit(Order(1, "alice", 1, "SELL", 100, 2))
    assert book.cancel(1) == 2
    # The old 100 price is still in the lazy heap. Reuse, don't duplicate.
    book.submit(Order(2, "bob", 1, "SELL", 100, 3))
    result = book.submit(Order(3, "carol", 1, "BUY", 110, 3))
    assert [(x.price_ticks, x.quantity) for x in result.fills] == [(100, 3)]
    assert book.depth(1, "SELL") == []
    book.assert_internal_invariants()


def test_duplicate_order_id_rejected():
    book = OrderBook()
    book.submit(Order(1, "alice", 1, "BUY", 100, 1))
    book.cancel(1)
    with pytest.raises(ValueError, match="Duplicate"):
        book.submit(Order(1, "bob", 1, "SELL", 99, 1))


@pytest.mark.parametrize("bad", [
    Order(0, "alice", 1, "BUY", 100, 1),
    Order(1, "", 1, "BUY", 100, 1),
    Order(1, "alice", 1, "HOLD", 100, 1),
    Order(1, "alice", 1, "BUY", 0, 1),
    Order(1, "alice", 1, "BUY", 100, -1),
    Order(1, "alice", 0, "BUY", 100, 1),
    Order(1, "alice", 1, "BUY", 100.5, 1),
])
def test_invalid_orders_rejected(bad):
    with pytest.raises(ValueError):
        OrderBook().submit(bad)


@pytest.mark.parametrize("seed", [11, 2026, 4321, 99991])
def test_randomized_differential_matching(seed):
    rng = Random(seed)
    fast = OrderBook()
    slow = ReferenceBook()
    for order_id in range(1, 2001):
        if slow.active and rng.random() < 0.27:
            cancel_id = rng.choice(slow.active)[0].order_id
            assert fast.cancel(cancel_id) == slow.cancel(cancel_id)
        incoming = Order(
            order_id=order_id,
            trader_id=str(rng.randint(1, 7)),
            instrument_id=rng.choice((1, 2, 3)),
            side=rng.choice(("BUY", "SELL")),
            price_ticks=rng.randint(95, 107),
            quantity=rng.randint(1, 30),
        )
        got = fast.submit(incoming)
        expected = slow.submit(incoming)
        assert got == expected, (seed, order_id, got, expected)
        assert sum(x.quantity for x in got.fills) + got.remaining == incoming.quantity
        assert all(x.buy_trader_id != x.sell_trader_id for x in got.fills)
        for instrument_id in (1, 2, 3):
            for side in ("BUY", "SELL"):
                assert fast.depth(instrument_id, side) == slow.depth(instrument_id, side), (
                    seed, order_id, instrument_id, side
                )
        fast.assert_internal_invariants()
