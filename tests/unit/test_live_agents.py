from dataclasses import replace
from decimal import Decimal
import random
import pytest
from backend.simulator.agents import (
    AccountState, ActiveOrder, TradingAgent, MarketMakerAgent, NoiseTraderAgent,
    MomentumTraderAgent, MeanReversionAgent, PlaceOrderAction, CancelOrderAction, HoldAction,
)
from backend.simulator.market_model import MarketObservation, SyntheticMarketModel, MAX_PRICE

OBS = MarketObservation(1, 1000, 995, 1005, ((995, 10),), ((1005, 20),), (980, 990, 1000), 5, 10)
ACCOUNT = AccountState(10_000_000, 0, Decimal('2.5'))


@pytest.mark.parametrize('volatility', ['low', 'medium', 'high'])
def test_model_reproducible_bounded_and_local(volatility):
    state = random.getstate()
    a, b = SyntheticMarketModel(42, volatility), SyntheticMarketModel(42, volatility)
    values = [a.next_reference_price(1, 1000) for _ in range(100)]
    assert values == [b.next_reference_price(1, 1000) for _ in range(100)]
    assert min(values) < 1000 < max(values) and 1000 in values
    for initial in (1, MAX_PRICE):
        price = initial
        for _ in range(1000):
            price = a.next_reference_price(initial + 1, price)
            assert 1 <= price <= MAX_PRICE
    assert random.getstate() == state


@pytest.mark.parametrize('cls', [MarketMakerAgent, NoiseTraderAgent, MomentumTraderAgent, MeanReversionAgent])
def test_strategy_reproducibility_and_alignment(cls):
    a, b = cls('bot', 1, 7), cls('bot', 1, 7)
    actions = [a.decide(OBS, ACCOUNT, ()) for _ in range(100)]
    assert actions == [b.decide(OBS, ACCOUNT, ()) for _ in range(100)]
    for action in actions:
        if isinstance(action, PlaceOrderAction):
            assert 1 <= action.price_ticks <= MAX_PRICE
            assert action.quantity > 0 and action.quantity % OBS.lot_size == 0
            assert action.price_ticks * OBS.tick_size * action.quantity <= 1_000_000


def test_maker_passive_two_sides_stale_replacement_no_accumulation():
    agent = MarketMakerAgent('bot', 1, 1)
    buy = agent.decide(OBS, ACCOUNT, ())
    assert isinstance(buy, PlaceOrderAction) and buy.side == 'BUY' and buy.price_ticks < OBS.best_ask_ticks
    orders = (ActiveOrder(1, buy.side, buy.price_ticks, buy.quantity),)
    sell = agent.decide(OBS, ACCOUNT, orders)
    assert isinstance(sell, PlaceOrderAction) and sell.side == 'SELL' and sell.price_ticks > OBS.best_bid_ticks
    orders += (ActiveOrder(2, sell.side, sell.price_ticks, sell.quantity),)
    assert isinstance(agent.decide(OBS, ACCOUNT, orders), HoldAction)
    assert isinstance(agent.decide(replace(OBS, reference_price_ticks=1200), ACCOUNT, orders), CancelOrderAction)


def test_noise_produces_aggressive_passive_holds_cancels_and_irregular_intervals():
    agent = NoiseTraderAgent('bot', 1, 33)
    actions = [agent.decide(OBS, ACCOUNT, ()) for _ in range(300)]
    places = [a for a in actions if isinstance(a, PlaceOrderAction)]
    assert {a.side for a in places} == {'BUY', 'SELL'}
    assert len({a.quantity for a in places}) > 1
    assert any(a.price_ticks == (OBS.best_ask_ticks if a.side == 'BUY' else OBS.best_bid_ticks) for a in places)
    assert any(a.price_ticks < OBS.best_ask_ticks for a in places if a.side == 'BUY')
    assert any(isinstance(a, HoldAction) for a in actions)
    orders = (ActiveOrder(5, 'BUY', 990, 10),) * 4
    assert isinstance(agent.decide(OBS, ACCOUNT, orders), CancelOrderAction)
    assert len({agent.decision_interval() for _ in range(10)}) > 1


@pytest.mark.parametrize('trend,side', [((990, 1000, 1010), 'BUY'), ((1010, 1000, 990), 'SELL')])
def test_momentum_bias(trend, side):
    agent = MomentumTraderAgent('bot', 1, 1)
    actions = [agent.decide(replace(OBS, recent_settled_prices=trend), ACCOUNT, ()) for _ in range(200)]
    assert sum(a.side == side for a in actions) > 140


@pytest.mark.parametrize('prices,side', [((1000, 1000, 950), 'BUY'), ((1000, 1000, 1050), 'SELL')])
def test_reversion_direction(prices, side):
    action = MeanReversionAgent('bot', 1, 2).decide(replace(OBS, recent_settled_prices=prices), ACCOUNT, ())
    assert isinstance(action, PlaceOrderAction) and action.side == side


@pytest.mark.parametrize('side', ['BUY', 'SELL'])
def test_collateral_exposure_and_self_cross_safety(side):
    agent = TradingAgent('bot', 1, 1)
    assert isinstance(agent.place(OBS, replace(ACCOUNT, cash_balance=0), (), side, 1000), HoldAction)
    inventory = 100 * OBS.lot_size * (1 if side == 'BUY' else -1)
    assert isinstance(agent.place(OBS, replace(ACCOUNT, net_quantity=inventory), (), side, 1000), HoldAction)
    opposite = (ActiveOrder(1, 'SELL' if side == 'BUY' else 'BUY', 1000, 10),)
    assert isinstance(agent.place(OBS, ACCOUNT, opposite, side, 1000), HoldAction)
    assert isinstance(agent.place(replace(OBS, reference_price_ticks=MAX_PRICE), ACCOUNT, (), side, MAX_PRICE), HoldAction)


def test_pending_orders_bound_future_exposure_and_fees_are_budgeted():
    agent = TradingAgent('bot', 1, 1)
    orders = (ActiveOrder(1, 'BUY', 990, 990),)
    action = agent.place(OBS, ACCOUNT, orders, 'BUY', 1000, 5)
    assert action.quantity == 10
    assert isinstance(agent.place(OBS, replace(ACCOUNT, cash_balance=50000), (), 'BUY', 1000), HoldAction)
    assert isinstance(agent.place(OBS, replace(ACCOUNT, cash_balance=50013), (), 'BUY', 1000), PlaceOrderAction)


@pytest.mark.parametrize('book', [dict(best_bid_ticks=2000), dict(best_ask_ticks=1)])
def test_maker_holds_when_external_book_prevents_a_bounded_passive_spread(book):
    action = MarketMakerAgent('bot',1,1).decide(replace(OBS, **book), ACCOUNT, ())
    assert isinstance(action, HoldAction)
