"""Pure synthetic reference process. References are never reported as executions."""
from dataclasses import dataclass
import random

MAX_PRICE = 2**53 - 1  # exact sorted-set scores in the existing Redis adapter
BookLevels = tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class MarketObservation:
    instrument_id: int
    reference_price_ticks: int
    best_bid_ticks: int | None
    best_ask_ticks: int | None
    bid_levels: BookLevels
    ask_levels: BookLevels
    recent_settled_prices: tuple[int, ...]
    tick_size: int
    lot_size: int


class SyntheticMarketModel:
    def __init__(self, seed: int, volatility: str):
        if volatility not in ('low', 'medium', 'high'):
            raise ValueError('Unsupported volatility')
        self.rng = random.Random(seed)
        self.volatility = volatility
        self.anchors = {}

    def next_reference_price(self, instrument_id: int, current_price_ticks: int) -> int:
        if type(current_price_ticks) is not int or not 1 <= current_price_ticks <= MAX_PRICE:
            raise ValueError('Reference outside supported price range')
        anchor = self.anchors.setdefault(instrument_id, current_price_ticks)
        # Integer arithmetic stays exact even at the adapter limit. Local moves
        # and session-wide excursions are both bounded, including at price 1.
        scale = {'low': 1, 'medium': 3, 'high': 8}[self.volatility]
        step = max(1, current_price_ticks * scale // 10000)
        shock = self.rng.choice((-2, -1, 0, 1, 2)) * step
        return max(max(1, anchor // 2), min(MAX_PRICE, anchor + anchor // 2 + 1,
                                           current_price_ticks + shock))
