"""Rule-based decisions only: no I/O, credentials, or matching-engine access."""
from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
from random import Random
from typing import Literal

from backend.simulator.market_model import MAX_PRICE, MarketObservation

MAX_ORDERS = 4
MAX_INVENTORY_LOTS = 100
MAX_ORDER_NOTIONAL = 1_000_000


@dataclass(frozen=True)
class PlaceOrderAction:
    instrument_id: int
    side: Literal['BUY', 'SELL']
    price_ticks: int
    quantity: int


@dataclass(frozen=True)
class CancelOrderAction:
    order_id: int


@dataclass(frozen=True)
class HoldAction:
    reason: str


Action = PlaceOrderAction | CancelOrderAction | HoldAction


@dataclass(frozen=True)
class AccountState:
    cash_balance: int
    net_quantity: int
    max_fee_bps: Decimal


@dataclass(frozen=True)
class ActiveOrder:
    order_id: int
    side: str
    price_ticks: int
    remaining_quantity: int


class TradingAgent:
    def __init__(self, trader_id, instrument_id, seed):
        self.trader_id = trader_id
        self.instrument_id = instrument_id
        self.rng = Random(seed)

    def decision_interval(self):
        """Irregular eligibility; the supervisor additionally enforces a global rate."""
        return self.rng.uniform(0.5, 2.0)

    def decide(self, observation, account_state, active_orders) -> Action:
        raise NotImplementedError

    def place(self, obs: MarketObservation, account: AccountState, orders,
              side, price, lots=1) -> Action:
        if obs.instrument_id != self.instrument_id or len(orders) >= MAX_ORDERS:
            return HoldAction('Outstanding order or instrument limit')
        if type(price) is not int or not 1 <= price <= MAX_PRICE or side not in ('BUY', 'SELL'):
            return HoldAction('Invalid price or side')
        if obs.tick_size <= 0 or obs.lot_size <= 0:
            return HoldAction('Invalid metadata')
        if any(o.side != side and (price >= o.price_ticks if side == 'BUY'
                                  else price <= o.price_ticks) for o in orders):
            return HoldAction('Own opposite quote would cross')
        if any(o.side == side and o.price_ticks == price for o in orders):
            return HoldAction('Quote already present')
        # Bound worst-case inventory even if every same-side order fills.
        pending = sum(o.remaining_quantity for o in orders if o.side == side)
        capacity = MAX_INVENTORY_LOTS * obs.lot_size - pending - (
            account.net_quantity if side == 'BUY' else -account.net_quantity)
        notional_per_lot = price * obs.tick_size * obs.lot_size
        max_lots = min(5, max(0, lots), capacity // obs.lot_size,
                       MAX_ORDER_NOTIONAL // notional_per_lot)
        for count in range(max_lots, 0, -1):
            qty = count * obs.lot_size
            value = price * obs.tick_size * qty
            fee = int((Decimal(value) * account.max_fee_bps / 10000).to_integral_value(rounding=ROUND_CEILING))
            if value + fee <= min(account.cash_balance, 2**63 - 1):
                return PlaceOrderAction(self.instrument_id, side, price, qty)
        return HoldAction('Insufficient collateral or bounded exposure')

    def maintenance(self, orders):
        if len(orders) >= MAX_ORDERS or (orders and self.rng.random() < 0.15):
            return CancelOrderAction(orders[0].order_id)
        return None


class MarketMakerAgent(TradingAgent):
    def decide(self, observation, account_state, active_orders):
        ref = observation.reference_price_ticks
        half_spread = max(1, min(20, ref // 200))
        bid, ask = max(1, ref - half_spread), min(MAX_PRICE, ref + half_spread)
        if bid >= ask:
            return HoldAction('No valid spread')
        # Keep passive quotes outside actual opposing liquidity, including humans.
        if observation.best_ask_ticks is not None:
            bid = min(bid, observation.best_ask_ticks - 1)
        if observation.best_bid_ticks is not None:
            ask = max(ask, observation.best_bid_ticks + 1)
        for order in active_orders:
            target = bid if order.side == 'BUY' else ask
            if abs(order.price_ticks - target) > half_spread * 2:
                return CancelOrderAction(order.order_id)
        if not 1 <= bid < ask <= MAX_PRICE or ask - bid > 2 * half_spread:
            return HoldAction('No bounded passive spread around the reference')
        for side, price in (('BUY', bid), ('SELL', ask)):
            if not any(o.side == side for o in active_orders):
                action = self.place(observation, account_state, active_orders, side, price, 2)
                if isinstance(action, PlaceOrderAction):
                    return action
        return HoldAction('Two-sided quotes maintained or collateral unavailable')


class NoiseTraderAgent(TradingAgent):
    def decide(self, observation, account_state, active_orders):
        maintenance = self.maintenance(active_orders)
        if maintenance:
            return maintenance
        if self.rng.random() < 0.15:
            return HoldAction('Noise pause')
        side = self.rng.choice(('BUY', 'SELL'))
        aggressive = self.rng.random() < 0.45
        quote = observation.best_ask_ticks if side == 'BUY' else observation.best_bid_ticks
        price = quote if aggressive and quote is not None else max(1, min(MAX_PRICE,
            observation.reference_price_ticks + (-1 if side == 'BUY' else 1) * self.rng.randint(1, 10)))
        return self.place(observation, account_state, active_orders, side, price, self.rng.randint(1, 5))


class MomentumTraderAgent(TradingAgent):
    def decide(self, observation, account_state, active_orders):
        maintenance = self.maintenance(active_orders)
        if maintenance:
            return maintenance
        prices = observation.recent_settled_prices
        if len(prices) < 2 or prices[-1] == prices[0]:
            return HoldAction('No settled trend')
        up = prices[-1] > prices[0]
        side = 'BUY' if self.rng.random() < (0.8 if up else 0.2) else 'SELL'
        price = observation.best_ask_ticks if side == 'BUY' else observation.best_bid_ticks
        return self.place(observation, account_state, active_orders, side,
                          price or observation.reference_price_ticks, self.rng.randint(1, 3))


class MeanReversionAgent(TradingAgent):
    def decide(self, observation, account_state, active_orders):
        maintenance = self.maintenance(active_orders)
        if maintenance:
            return maintenance
        prices = observation.recent_settled_prices
        if not prices:
            return HoldAction('No committed price')
        reference = sum(prices) // len(prices)
        threshold = max(1, reference // 200)
        delta = prices[-1] - reference
        if abs(delta) <= threshold:
            return HoldAction('Neutral deviation')
        side = 'BUY' if delta < 0 else 'SELL'
        price = observation.best_ask_ticks if side == 'BUY' else observation.best_bid_ticks
        return self.place(observation, account_state, active_orders, side,
                          price or prices[-1], self.rng.randint(1, 3))
