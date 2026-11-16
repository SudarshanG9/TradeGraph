"""Lifecycle boundary tests. Native trading correctness is tested separately."""
import asyncio
from decimal import Decimal
from types import SimpleNamespace
import time
import subprocess
import sys
import pytest
from psycopg.errors import RaiseException
from backend.simulator.agents import HoldAction, PlaceOrderAction, TradingAgent, CancelOrderAction
from backend.simulator.live_supervisor import (
    LiveMarketSupervisor, LiveSimulationConfig, SimulationConflict, SimulationState,
)
from scripts.seed_live_bots import load_bot_specs


class FakeDatabase:
    def __init__(self):
        self.orders = {}

    def query(self, sql, params=()):
        if 'FROM instrument WHERE' in sql:
            return [dict(id=i, tick_size=1, lot_size=1, is_active=i != 999) for i in params[0]]
        if 'FROM user_account u' in sql:
            return [dict(email=s.email, role='TRADER', trader_id=s.email, full_name=s.name,
                         desk_name='Equities', margin_id=s.email, tier_name='STANDARD') for s in load_bot_specs()]
        if 'LIMIT 1' in sql and 'FROM public."order"' in sql:
            return []
        if 'FROM margin_account m' in sql:
            return [dict(cash_balance=100000, max_fee_bps=Decimal(2), net_quantity=0)]
        if 'count(*)' in sql:
            return [dict(n=0)]
        if 'FROM execution' in sql:
            return []
        if 'FROM public."order"' in sql:
            return [dict(r) for i,r in self.orders.items() if i in params[0]]
        raise AssertionError(sql)


class FakeCoordinator:
    def __init__(self, db):
        self.db = db
        self.dispatcher = SimpleNamespace(queue=asyncio.Queue(100), failure=None)
        self.worker = SimpleNamespace(task=SimpleNamespace(done=lambda: False), drain=self.drain)
        self.closing = False
        self.derived = {}
        self.submissions = []
        self.cancelled = []
        self.entered = asyncio.Event()
        self.release = None

    def verify_owner(self):
        return True

    async def drain(self):
        pass

    def book_snapshot(self, instrument):
        return dict(bids=[], asks=[])

    async def admit(self, trader_id, request, request_key):
        self.entered.set()
        if self.release:
            await self.release.wait()
        oid = len(self.db.orders) + 1
        self.db.orders[oid] = dict(id=oid, trader_id=trader_id, status='OPEN', filled_quantity=0, **request.model_dump())
        self.submissions.append(request_key)
        return self.db.orders[oid]

    async def cancel(self, order_id, trader_id):
        assert self.db.orders[order_id]['trader_id'] == trader_id
        self.db.orders[order_id]['status'] = 'CANCELLED'
        self.cancelled.append(order_id)
        return 1


class TestAgent(TradingAgent):
    __test__ = False

    def decide(self, observation, account, active):
        return HoldAction('already quoted') if active else PlaceOrderAction(self.instrument_id, 'BUY', 100, 1)


def setup():
    db = FakeDatabase()
    c = FakeCoordinator(db)
    s = LiveMarketSupervisor(c, db, agent_factory=lambda spec, tid, iid, seed: TestAgent(tid, iid, seed))
    return s, c, db


def test_start_duplicate_stop_repeat_and_no_human_cancellation():
    async def run():
        s,c,db = setup()
        assert (await s.status())['state'] == 'STOPPED'
        results = await asyncio.gather(s.start(LiveSimulationConfig((1,))), s.start(LiveSimulationConfig((1,))), return_exceptions=True)
        assert sum(isinstance(r, SimulationConflict) for r in results) == 1
        await asyncio.wait_for(c.entered.wait(), 2)
        db.orders[999] = dict(id=999, trader_id='human', instrument_id=1, side='BUY', price_ticks=50, quantity=1, filled_quantity=0, status='OPEN')
        result = await s.stop()
        assert result['state'] == 'STOPPED' and result['active_bot_orders'] == 0
        assert 999 not in c.cancelled and db.orders[999]['status'] == 'OPEN'
        assert c.submissions and len(set(c.submissions)) == len(c.submissions)
        assert (await s.stop())['state'] == 'STOPPED'
        assert s.task.done()
        old_task = s.task
        await s.start(LiveSimulationConfig((1,)))
        assert s.task is not old_task
        await s.shutdown()
    asyncio.run(run())


def test_stop_waits_for_admission_and_survives_caller_disconnect():
    async def run():
        s,c,_ = setup()
        c.release = asyncio.Event()
        await s.start(LiveSimulationConfig((1,)))
        await asyncio.wait_for(c.entered.wait(), 2)
        stop = asyncio.create_task(s.stop())
        await asyncio.sleep(0)
        assert not stop.done() and s.state == SimulationState.STOPPING
        with pytest.raises(SimulationConflict):
            await s.start(LiveSimulationConfig((1,)))
        stop.cancel()
        with pytest.raises(asyncio.CancelledError):
            await stop
        assert not s.task.cancelled()
        c.release.set()
        result = await s.stop()
        assert result['orders_accepted'] == result['orders_cancelled'] == 1
        assert result['state'] == 'STOPPED'
    asyncio.run(run())


def test_expiry_rate_limit_failure_and_error_restart_refusal():
    async def run():
        s,c,_ = setup()
        await s.start(LiveSimulationConfig((1,), orders_per_second=5))
        s.deadline = time.monotonic() + 0.45
        await asyncio.wait_for(s.task, 2)
        assert len(c.submissions) <= 3
        assert s.state == SimulationState.STOPPED and s.task.done()
        await s.start(LiveSimulationConfig((1,)))
        c.dispatcher.failure = 'unhealthy'
        await s.stop()
        assert s.state == SimulationState.ERROR and s.last_error
        with pytest.raises(SimulationConflict):
            await s.start(LiveSimulationConfig((1,)))
    asyncio.run(run())


@pytest.mark.parametrize('kwargs', [dict(bot_count=3), dict(bot_count=9), dict(orders_per_second=6),
    dict(max_duration_seconds=29), dict(max_duration_seconds=601), dict(volatility='extreme'),
    dict(instrument_ids=(1,1)), dict(instrument_ids=()), dict(seed=True)])
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        LiveSimulationConfig(**(dict(instrument_ids=(1,)) | kwargs))


def test_invalid_instrument_and_missing_worker_leave_stopped():
    async def run():
        s,c,_ = setup()
        with pytest.raises(ValueError):
            await s.start(LiveSimulationConfig((999,)))
        assert s.state == SimulationState.STOPPED
        c.worker = None
        with pytest.raises(RuntimeError):
            await s.start(LiveSimulationConfig((1,)))
        assert s.task is None
    asyncio.run(run())


def test_rejected_reservation_is_counted_without_new_funds_or_loop_failure():
    async def run():
        s,c,_ = setup()
        async def reject(*args, **kwargs):
            c.entered.set()
            raise RaiseException('Insufficient available funds')
        c.admit = reject
        await s.start(LiveSimulationConfig((1,)))
        await asyncio.wait_for(c.entered.wait(), 2)
        result = await s.stop()
        assert result['state'] == 'STOPPED'
        assert result['orders_attempted'] == result['orders_rejected'] == 1
        assert not s.accepted
    asyncio.run(run())


def test_expired_slow_observation_cannot_admit_another_order():
    async def run():
        s,c,_ = setup()
        original = s._observe_market
        async def slow_observation(iid):
            observation = await original(iid)
            s.deadline = time.monotonic() - 1
            return observation
        s._observe_market = slow_observation
        await s.start(LiveSimulationConfig((1,)))
        await asyncio.wait_for(s.task, 2)
        assert not c.submissions
        assert s.state == SimulationState.STOPPED
    asyncio.run(run())


@pytest.mark.parametrize('condition', ['queue', 'redis', 'neo4j'])
def test_pressure_throttles_and_reports_real_worker_state(condition):
    async def run():
        s,c,_ = setup()
        if condition == 'queue':
            for _ in range(50):
                c.dispatcher.queue.put_nowait(object())
        else:
            c.derived[condition] = SimpleNamespace(failed='retry pending')
        original_wait = s._wait
        async def accelerated_wait(seconds):
            await original_wait(0)  # exercise ten scheduling turns without wall-clock delay
        s._wait = accelerated_wait
        await s.start(LiveSimulationConfig((1,)))
        await asyncio.wait_for(s.task, 2)
        result = await s.status()
        assert result['backpressure_events'] == 10 and not c.submissions
        assert result['state'] == 'ERROR'
        if condition != 'queue':
            assert result['derived_workers'][condition] == 'retrying'
    asyncio.run(run())


def test_stop_never_reports_success_before_settlement_drain():
    async def run():
        s,c,_ = setup()
        await s.start(LiveSimulationConfig((1,)))
        await asyncio.wait_for(c.entered.wait(), 2)
        entered, release = asyncio.Event(), asyncio.Event()
        async def gated_drain():
            entered.set()
            await release.wait()
        c.worker.drain = gated_drain
        stopping = asyncio.create_task(s.stop())
        await asyncio.wait_for(entered.wait(), 2)
        assert not stopping.done()
        assert (await s.status())['state'] == 'STOPPING'
        release.set()
        assert (await stopping)['state'] == 'STOPPED'
    asyncio.run(run())


def test_bad_identity_and_human_cancel_actions_are_rejected():
    async def run():
        s,c,_ = setup()
        await s.start(LiveSimulationConfig((1,)))
        await asyncio.wait_for(c.entered.wait(), 2)
        with pytest.raises(ValueError,match='OWNER'):
            await s._execute_action(s.agents[0], CancelOrderAction(999))
        with pytest.raises(ValueError,match='IDENTITY'):
            await s._execute_action(TestAgent('human',1,1), PlaceOrderAction(1,'BUY',100,1))
        assert not c.cancelled
        await s.stop()
    asyncio.run(run())


@pytest.mark.parametrize('conflict', ['missing', 'role', 'margin', 'name', 'outstanding'])
def test_unverified_or_unresolved_bot_accounts_refuse_start(conflict):
    async def run():
        s,c,db = setup()
        original = db.query
        def query(sql, params=()):
            rows = original(sql,params)
            if 'FROM user_account u' in sql:
                if conflict == 'missing':
                    return rows[:-1]
                field = {'role':'role','margin':'margin_id','name':'full_name'}.get(conflict)
                if field:
                    rows[0][field] = None
            if conflict == 'outstanding' and 'LIMIT 1' in sql and 'FROM public."order"' in sql:
                return [dict(id=99)]
            return rows
        db.query = query
        with pytest.raises((ValueError,SimulationConflict)):
            await s.start(LiveSimulationConfig((1,)))
        assert s.state == SimulationState.STOPPED and s.task is None
    asyncio.run(run())


def test_runtime_allowlist_import_does_not_load_admin_environment():
    code = '''
import dotenv
def forbidden(*args, **kwargs):
    raise AssertionError('Runtime allowlist imported administrative environment loading')
dotenv.load_dotenv = forbidden
from scripts.seed_live_bots import load_bot_specs
assert len(load_bot_specs()) == 8
'''
    subprocess.run([sys.executable,'-c',code],check=True,capture_output=True,text=True)


def test_decisions_do_not_recount_execution_history_on_every_tick():
    async def run():
        s,c,db = setup()
        counts = []
        original = db.query
        def query(sql, params=()):
            if 'count(*)' in sql and 'FROM execution' in sql:
                counts.append(sql)
            return original(sql,params)
        db.query = query
        await s.start(LiveSimulationConfig((1,)))
        await asyncio.wait_for(c.entered.wait(), 2)
        await s._reconcile()
        await s._reconcile()
        assert not counts
        await s.status()
        assert len(counts) == 1
        await s.stop()
    asyncio.run(run())


def test_error_recovery_requires_finished_task_healthy_pipeline_and_terminal_orders():
    async def run():
        s,c,db=setup()
        await s.start(LiveSimulationConfig((1,)))
        await c.entered.wait();await s.stop()
        s.state=SimulationState.ERROR;s.last_error='transient pressure'
        old=s.task
        assert (await s.recover())['state']=='STOPPED'
        assert s.task is old and old.done()
        await s.start(LiveSimulationConfig((1,)));await s.stop()
        s.state=SimulationState.ERROR
        s.task=asyncio.create_task(asyncio.sleep(30))
        with pytest.raises(SimulationConflict): await s.recover()
        s.task.cancel()
        try: await s.task
        except asyncio.CancelledError: pass
        c.dispatcher.failure='unresolved financial event'
        with pytest.raises(RuntimeError): await s.recover()
        c.dispatcher.failure=None
        oid=next(iter(s.accepted),None)
        if oid:
            db.orders[oid]['status']='OPEN'
            with pytest.raises(SimulationConflict): await s.recover()
        assert s.state==SimulationState.ERROR
    asyncio.run(run())
