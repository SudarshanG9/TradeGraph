"""Pure single-thread matching owner; admission I/O belongs to the gateway."""
from collections import defaultdict
from threading import get_ident
from datetime import datetime, timezone
from struct import pack

from backend.matching.order_book import OrderBook
from backend.matching.fenwick import PriceVolumeIndex
from backend.matching.rolling_vwap import RollingVWAP


class Engine:
    def __init__(self, window=100, *, monotonic_order_ids=False):
        self.book = OrderBook(monotonic_ids=monotonic_order_ids)
        self.owner = get_ident()
        self.window = window
        self.volume = defaultdict(PriceVolumeIndex)
        self.vwap = defaultdict(lambda: RollingVWAP(window))
        self.settled = {}
        self.latest_time = {}

    def _check_owner(self):
        if get_ident() != self.owner:
            raise RuntimeError("Matching requires its single owner thread")

    def submit(self, order):
        self._check_owner()
        return self.book.submit(order)

    def cancel(self, order_id):
        self._check_owner()
        return self.book.cancel(order_id)

    @staticmethod
    def event_identity(event):
        # Exact fixed-width payload, not a probabilistic digest or evicting cache.
        elapsed = event.occurred_at - datetime(1970,1,1,tzinfo=timezone.utc)
        micros = (elapsed.days * 86400 + elapsed.seconds) * 1000000 + elapsed.microseconds
        return pack('>iqq16s16sqqqq',event.instrument_id,event.buy_order_id,event.sell_order_id,
                    event.buy_trader_id.bytes,event.sell_trader_id.bytes,event.price_ticks,
                    event.quantity,event.taker_order_id,micros)

    def has_settled(self,event):
        return self.settled.get(event.event_id) == self.event_identity(event)

    def apply_settled(self, event):
        self._check_owner()
        identity = self.event_identity(event)
        if event.event_id in self.settled:
            if self.settled[event.event_id] != identity:
                raise ValueError("Conflicting settled event")
            return False
        self.volume[event.instrument_id].add(event.price_ticks, event.quantity)
        self.vwap[event.instrument_id].add(event.price_ticks, event.quantity)
        self.settled[event.event_id] = identity
        previous=self.latest_time.get(event.instrument_id)
        self.latest_time[event.instrument_id]=max(previous,event.occurred_at) if previous else event.occurred_at
        return True
