"""One bounded event-loop task using the application's existing trading owner."""
import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import time
from uuid import uuid4

import psycopg

from backend.api.routes.orders import NewOrder
from backend.simulator.agents import (
    AccountState, ActiveOrder, CancelOrderAction, HoldAction, PlaceOrderAction,
    MarketMakerAgent, NoiseTraderAgent, MomentumTraderAgent, MeanReversionAgent,
    MAX_ORDERS, MAX_INVENTORY_LOTS, MAX_ORDER_NOTIONAL,
)
from backend.simulator.market_model import MAX_PRICE, MarketObservation, SyntheticMarketModel
from scripts.seed_live_bots import load_bot_specs


class SimulationState(str, Enum):
    STOPPED = 'STOPPED'
    RUNNING = 'RUNNING'
    STOPPING = 'STOPPING'
    ERROR = 'ERROR'


class SimulationConflict(RuntimeError):
    pass


class SimulationUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class LiveSimulationConfig:
    instrument_ids: tuple[int, ...]
    bot_count: int = 8
    orders_per_second: int = 2
    volatility: str = 'medium'
    seed: int = 20261115
    max_duration_seconds: int = 300

    def __post_init__(self):
        if (type(self.instrument_ids) is not tuple or not 1 <= len(self.instrument_ids) <= 3
            or len(set(self.instrument_ids)) != len(self.instrument_ids)
            or any(type(i) is not int or not 1 <= i < 2**31 for i in self.instrument_ids)):
            raise ValueError('INVALID_INSTRUMENTS')
        for value, low, high in ((self.bot_count, 4, len(load_bot_specs())),
                                 (self.orders_per_second, 1, 5),
                                 (self.max_duration_seconds, 30, 600),
                                 (self.seed, 0, 2**63 - 1)):
            if type(value) is not int or not low <= value <= high:
                raise ValueError('INVALID_SIMULATION_CONFIG')
        if self.volatility not in ('low', 'medium', 'high'):
            raise ValueError('INVALID_VOLATILITY')


def build_agent(spec, trader_id, instrument_id, seed):
    cls = {'mm': MarketMakerAgent, 'noise': NoiseTraderAgent,
           'momentum': MomentumTraderAgent, 'reversion': MeanReversionAgent}[spec.strategy]
    return cls(trader_id, instrument_id, seed)


class LiveMarketSupervisor:
    def __init__(self, coordinator, database, *, agent_factory=build_agent):
        self.coordinator, self.database = coordinator, database
        self.agent_factory = agent_factory  # internal deterministic integration seam, never HTTP input
        self.state = SimulationState.STOPPED
        self.state_lock = asyncio.Lock()
        self.task = None
        self.stop_event = asyncio.Event()
        self.config = None
        self.run_id = None
        self.started_at = self.stopped_at = self.last_action_at = self.last_error = None
        self.agents = []
        self.accepted = {}  # exact order ID -> trusted owner, retained after stop
        self.active = []
        self.committed_executions = 0
        self.metrics = dict(orders_attempted=0, orders_accepted=0, orders_rejected=0,
                            orders_cancelled=0, backpressure_events=0)

    async def _query(self, sql, params=()):
        return await asyncio.to_thread(self.database.query, sql, params)

    def _ensure_available(self):
        worker = self.coordinator.worker
        if (self.coordinator.closing or self.coordinator.dispatcher.failure or not worker
            or not worker.task or worker.task.done()):
            raise SimulationUnavailable('TRADING_UNAVAILABLE')

    async def _load_bots(self):
        specs = load_bot_specs()
        rows = await self._query('''SELECT u.email,u.role,t.id AS trader_id,t.full_name,
            d.name AS desk_name,m.trader_id AS margin_id,f.tier_name
            FROM user_account u LEFT JOIN trader t ON t.user_account_id=u.id
            LEFT JOIN desk d ON d.id=t.desk_id LEFT JOIN margin_account m ON m.trader_id=t.id
            LEFT JOIN fee_tier f ON f.id=m.fee_tier_id WHERE u.email=ANY(%s)''',
            ([s.email for s in specs],))
        by_email = {r['email']: r for r in rows}
        for spec in specs:
            row = by_email.get(spec.email)
            if not row or not (row['role'] == 'TRADER' and row['trader_id'] and row['margin_id']
                               and row['full_name'] == spec.name and row['desk_name'] == 'Equities'
                               and row['tier_name'] == 'STANDARD'):
                raise ValueError('BOT_ACCOUNTS_NOT_PROVISIONED')
        ids = [by_email[s.email]['trader_id'] for s in specs]
        if len(set(ids)) != len(ids):
            raise ValueError('CONFLICTING_BOT_IDENTITIES')
        pending = await self._query('''SELECT id FROM public."order"
            WHERE trader_id=ANY(%s) AND status IN ('OPEN','PARTIAL') LIMIT 1''', (ids,))
        if pending:
            raise SimulationConflict('UNRESOLVED_BOT_ORDERS')
        return [(s, by_email[s.email]['trader_id']) for s in specs]

    async def start(self, config: LiveSimulationConfig):
        async with self.state_lock:
            if self.state != SimulationState.STOPPED:
                raise SimulationConflict('SIMULATOR_NOT_STOPPED')
            # Revalidate even for internal callers, before changing session state.
            if not isinstance(config, LiveSimulationConfig):
                raise ValueError('INVALID_SIMULATION_CONFIG')
            config.__post_init__()
            self._ensure_available()
            instruments = await self._query('SELECT id,tick_size,lot_size,is_active FROM instrument WHERE id=ANY(%s)',
                                            (list(config.instrument_ids),))
            if len(instruments) != len(config.instrument_ids) or not all(r['is_active'] for r in instruments):
                raise ValueError('INVALID_INSTRUMENTS')
            bots = await self._load_bots()
            self._ensure_available()
            agents = [self.agent_factory(spec, tid, config.instrument_ids[i % len(config.instrument_ids)], config.seed + i)
                      for i, (spec, tid) in enumerate(bots[:config.bot_count])]
            self.config = config
            self.instruments = {r['id']: r for r in instruments}
            self.agents = agents
            self.bot_ids = frozenset(tid for _, tid in bots[:config.bot_count])
            self.model = SyntheticMarketModel(config.seed, config.volatility)
            self.references = {}
            self.run_id = str(uuid4())
            self.accepted = {}
            self.active = []
            self.committed_executions = 0
            self.metrics = dict.fromkeys(self.metrics, 0)
            self.started_at = datetime.now(timezone.utc)
            self.stopped_at = self.last_action_at = self.last_error = None
            self.deadline = time.monotonic() + config.max_duration_seconds
            self.stop_event = asyncio.Event()
            self.state = SimulationState.RUNNING
            self.task = asyncio.create_task(self._run_loop(), name='tradegraph-live-market')
            return self._snapshot()

    async def stop(self):
        async with self.state_lock:
            if self.state == SimulationState.RUNNING:
                self.state = SimulationState.STOPPING
            self.stop_event.set()
            task = self.task
        # Shield the owned loop from HTTP disconnect/caller cancellation. Never
        # cancel a reservation, settlement or cancellation thread to stop sooner.
        if task is not None:
            await asyncio.shield(task)
        return self._snapshot()

    async def shutdown(self):
        return await self.stop()

    async def status(self):
        # Keep a run's order list and response consistent across a concurrent start.
        async with self.state_lock:
            if self.accepted:
                await self._reconcile(include_executions=True)
            return self._snapshot()

    def _snapshot(self):
        return dict(run_id=self.run_id, state=self.state.value, started_at=self.started_at,
                    stopped_at=self.stopped_at,
                    active_bots=len(self.agents) if self.state == SimulationState.RUNNING else 0,
                    instrument_ids=list(self.config.instrument_ids) if self.config else [],
                    config=asdict(self.config) if self.config else None,
                    **self.metrics, active_bot_orders=len(self.active),
                    committed_executions=self.committed_executions,
                    last_action_at=self.last_action_at, last_error=self.last_error,
                    derived_workers={name: ('retrying' if consumer.failed else 'ready'
                        if getattr(consumer, 'ready', True) else 'initializing')
                        for name, consumer in self.coordinator.derived.items()})

    async def _observe_market(self, instrument_id):
        book = self.coordinator.book_snapshot(instrument_id)  # owner loop only
        recent = await self._query('SELECT price_ticks FROM execution WHERE instrument_id=%s ORDER BY id DESC LIMIT 20',
                                   (instrument_id,))
        prices = tuple(r['price_ticks'] for r in reversed(recent))
        bids, asks = tuple(book['bids'][:20]), tuple(book['asks'][:20])
        # Empty-market bootstrap is explicitly synthetic, not a committed last price.
        initial = prices[-1] if prices else ((bids[0][0] + asks[0][0]) // 2
                    if bids and asks else bids[0][0] if bids else asks[0][0] if asks else 1000)
        reference = self.model.next_reference_price(instrument_id, self.references.get(instrument_id, min(MAX_PRICE, initial)))
        self.references[instrument_id] = reference
        metadata = self.instruments[instrument_id]
        return MarketObservation(instrument_id, reference, bids[0][0] if bids else None,
            asks[0][0] if asks else None, bids, asks, prices, metadata['tick_size'], metadata['lot_size'])

    async def _account(self, agent):
        rows = await self._query('''SELECT m.cash_balance,greatest(f.maker_fee_bps,f.taker_fee_bps) AS max_fee_bps,
            coalesce(p.net_quantity,0) AS net_quantity FROM margin_account m
            JOIN fee_tier f ON f.id=m.fee_tier_id LEFT JOIN position p
            ON p.trader_id=m.trader_id AND p.instrument_id=%s WHERE m.trader_id=%s''',
            (agent.instrument_id, agent.trader_id))
        if not rows:
            raise SimulationUnavailable('BOT_ACCOUNT_UNAVAILABLE')
        return AccountState(**rows[0])

    async def _reconcile(self, *, include_executions=False):
        accepted = dict(self.accepted)
        if not accepted:
            self.active = []
            return
        ids = list(accepted)
        rows = await self._query('''SELECT id,trader_id,instrument_id,side,price_ticks,quantity,filled_quantity,status
            FROM public."order" WHERE id=ANY(%s) UNION ALL
            SELECT id,trader_id,instrument_id,side,price_ticks,quantity,filled_quantity,status
            FROM order_history WHERE id=ANY(%s)''', (ids, ids))
        if (len(rows) != len(ids) or len({r['id'] for r in rows}) != len(ids)
            or any(r['trader_id'] != accepted[r['id']] for r in rows)):
            raise SimulationUnavailable('BOT_ORDER_RECONCILIATION_REQUIRED')
        self.active = [r for r in rows if r['status'] in ('OPEN', 'PARTIAL')]
        # Execution-order IDs have no dedicated index in the frozen schema.
        # Count only for requested status/final acceptance, never each decision.
        if include_executions:
            self.committed_executions = (await self._query('''SELECT count(*) AS n FROM execution
                WHERE buy_order_id=ANY(%s) OR sell_order_id=ANY(%s)''', (ids, ids)))[0]['n']

    def _orders_for(self, agent):
        return tuple(ActiveOrder(r['id'], r['side'], r['price_ticks'], r['quantity'] - r['filled_quantity'])
                     for r in self.active if r['trader_id'] == agent.trader_id)

    async def _cancel_owned(self, order_id, trader_id):
        if self.accepted.get(order_id) != trader_id:
            raise ValueError('INVALID_BOT_ORDER_OWNER')
        if not any(r['id'] == order_id for r in self.active):
            return
        try:
            quantity = await self.coordinator.cancel(order_id, trader_id)
        except ValueError:
            await self._reconcile()  # a human may have filled the quote since observation
            if any(r['id'] == order_id for r in self.active):
                raise
        else:
            if quantity:
                self.metrics['orders_cancelled'] += 1

    async def _execute_action(self, agent, action):
        if agent not in self.agents or agent.trader_id not in self.bot_ids:
            raise ValueError('INVALID_BOT_IDENTITY')
        if self.stop_event.is_set() or time.monotonic() >= self.deadline:
            return
        if isinstance(action, HoldAction):
            return
        self.last_action_at = datetime.now(timezone.utc)
        if isinstance(action, CancelOrderAction):
            await self._cancel_owned(action.order_id, agent.trader_id)
            return
        if not isinstance(action, PlaceOrderAction):
            raise ValueError('INVALID_AGENT_ACTION')
        meta = self.instruments[agent.instrument_id]
        orders = self._orders_for(agent)
        if (action.instrument_id != agent.instrument_id or action.instrument_id not in self.config.instrument_ids
            or type(action.price_ticks) is not int or not 1 <= action.price_ticks <= MAX_PRICE
            or type(action.quantity) is not int or not 0 < action.quantity <= 5 * meta['lot_size']
            or action.quantity % meta['lot_size'] or len(orders) >= MAX_ORDERS
            or action.price_ticks * meta['tick_size'] * action.quantity > MAX_ORDER_NOTIONAL):
            raise ValueError('INVALID_AGENT_ORDER')
        # Independently enforce exposure even for an injected internal strategy.
        account = await self._account(agent)
        pending = sum(o.remaining_quantity for o in orders if o.side == action.side)
        exposure = (account.net_quantity if action.side == 'BUY' else -account.net_quantity) + pending + action.quantity
        if (exposure > MAX_INVENTORY_LOTS * meta['lot_size'] or self.stop_event.is_set()
            or time.monotonic() >= self.deadline):
            return
        request = NewOrder(**asdict(action))
        self.metrics['orders_attempted'] += 1
        try:
            row = await self.coordinator.admit(agent.trader_id, request,
                request_key=f'live-{self.run_id}-{self.metrics["orders_attempted"]}')
        except psycopg.Error as exc:
            if exc.sqlstate not in ('P0001', '22023', '22003', '23514', '23503'):
                raise
            self.metrics['orders_rejected'] += 1
        except RuntimeError:
            self.metrics['orders_rejected'] += 1
            if self.coordinator.dispatcher.failure:
                raise
            self.metrics['backpressure_events'] += 1
        else:
            self.accepted[row['id']] = agent.trader_id
            self.metrics['orders_accepted'] += 1

    async def _wait(self, seconds):
        try:
            await asyncio.wait_for(self.stop_event.wait(), timeout=max(0, seconds))
        except TimeoutError:
            pass

    async def _run_loop(self):
        index = 0
        eligible = dict.fromkeys(self.bot_ids, 0.0)
        pressure_ticks = 0
        try:
            while not self.stop_event.is_set() and time.monotonic() < self.deadline:
                self._ensure_available()
                queue = self.coordinator.dispatcher.queue
                degraded = any(c.failed for c in self.coordinator.derived.values())
                if degraded or queue.qsize() >= max(1, queue.maxsize // 2):
                    self.metrics['backpressure_events'] += 1
                    pressure_ticks += 1
                    if pressure_ticks >= 10:
                        raise SimulationUnavailable('PIPELINE_BACKPRESSURE')
                else:
                    pressure_ticks = 0
                    agent = self.agents[index % len(self.agents)]
                    index += 1
                    if time.monotonic() >= eligible[agent.trader_id]:
                        await self._reconcile()
                        observation = await self._observe_market(agent.instrument_id)
                        account = await self._account(agent)
                        action = agent.decide(observation, account, self._orders_for(agent))
                        await self._execute_action(agent, action)
                        eligible[agent.trader_id] = time.monotonic() + agent.decision_interval()
                # No catch-up bursts after slow I/O. Expiry uses this same stop path.
                await self._wait(min(1 / self.config.orders_per_second,
                                     max(0, self.deadline - time.monotonic())))
        except asyncio.CancelledError:
            self.last_error = 'SIMULATOR_INTERRUPTED_RECONCILIATION_REQUIRED'
        except Exception:
            self.last_error = 'SIMULATOR_FAILED_RECONCILIATION_REQUIRED'
        finally:
            await self._finish_session_safely()

    async def _cancel_bot_orders(self):
        await self._reconcile()
        for row in tuple(self.active):
            await self._cancel_owned(row['id'], row['trader_id'])

    async def _finish_session_safely(self):
        async with self.state_lock:
            self.state = SimulationState.STOPPING
            self.stop_event.set()
        try:
            self._ensure_available()
            await self.coordinator.worker.drain()
            await self._cancel_bot_orders()
            await self.coordinator.worker.drain()
            await self._reconcile(include_executions=True)
            if self.active:
                raise SimulationUnavailable('UNRESOLVED_BOT_ORDERS')
        except Exception:
            self.last_error = 'STOP_FAILED_RECONCILIATION_REQUIRED'
        async with self.state_lock:
            self.stopped_at = datetime.now(timezone.utc)
            self.state = SimulationState.ERROR if self.last_error else SimulationState.STOPPED
