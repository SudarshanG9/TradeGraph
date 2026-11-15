"""Pure single-thread matching owner; admission I/O belongs to the gateway."""
from collections import defaultdict
from threading import get_ident

from backend.matching.order_book import OrderBook
from backend.matching.fenwick import PriceVolumeIndex
from backend.matching.rolling_vwap import RollingVWAP


class Engine:
    def __init__(self, window=100):
        self.book = OrderBook()
        self.owner = get_ident()
        self.window = window
        self.volume = defaultdict(PriceVolumeIndex)
        self.vwap = defaultdict(lambda: RollingVWAP(window))
        self.settled = {}

    def _check_owner(self):
        if get_ident() != self.owner:
            raise RuntimeError("Matching requires its single owner thread")

    def submit(self, order):
        self._check_owner()
        return self.book.submit(order)

    def cancel(self, order_id):
        self._check_owner()
        return self.book.cancel(order_id)

    def apply_settled(self, event):
        self._check_owner()
        if event.event_id in self.settled:
            if self.settled[event.event_id] != event:
                raise ValueError("Conflicting settled event")
            return False
        self.volume[event.instrument_id].add(event.price_ticks, event.quantity)
        self.vwap[event.instrument_id].add(event.price_ticks, event.quantity)
        self.settled[event.event_id] = event
        return True
