"""Global admission serialization includes reservation and PostgreSQL COMMIT."""
import asyncio
import psycopg
from datetime import datetime, timezone
from uuid import uuid4
from backend.events.dispatcher import Dispatcher, FailureKind
from backend.events.trade_event import TradeEvent
from backend.matching.engine import Engine
from backend.matching.order_book import Order


from backend.risk.request_identity import DuplicateRequest, RequestIdentityStore


class Coordinator:
    def __init__(self, database, settings):
        self.database = database
        self.settings = settings
        self.engine = Engine(monotonic_order_ids=True)
        self.lock = asyncio.Lock()
        self.dispatcher = Dispatcher(settings.event_queue_capacity)
        self.lease = database.acquire_owner()
        self.last_order_id = 0
        self.version = 0
        self.worker = None
        self.book_observers = []
        self.derived = {}
        self.epoch = str(uuid4())
        self.request_identities = RequestIdentityStore(database)
        self.closing = False

    def verify_owner(self):
        row = self.lease.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory' AND classid=((hashtext('tradegraph-matching-owner')::bigint >> 32) & 4294967295) AND objid=(hashtext('tradegraph-matching-owner')::bigint & 4294967295) AND granted) AS held").fetchone()
        if not row['held']:
            raise RuntimeError('Matching ownership lost; reconciliation required')
        return True

    async def committed_io(self, operation, *args):
        job=asyncio.create_task(asyncio.to_thread(operation,*args))
        try:
            return await asyncio.shield(job)
        except asyncio.CancelledError:
            # Cancellation cannot revoke a database COMMIT. Hold admission and
            # its owner lease until even repeated cancellation has a known end.
            while not job.done():
                try: await asyncio.shield(job)
                except asyncio.CancelledError: continue
                except Exception: break
            if job.done() and not job.cancelled():
                job.exception()  # retrieve any exception without masking cancellation
            raise

    async def finish_admissions(self):
        self.closing=True
        async with self.lock:
            pass  # waits for all shielded reservation/cancel threads before lease release

    def book_snapshot(self, instrument):
        return {'instrument_id':instrument,'version':self.version,'epoch':self.epoch,
                  'as_of':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
                  'bids':self.engine.book.depth(instrument,'BUY'),
                  'asks':self.engine.book.depth(instrument,'SELL')}

    def notify_book(self, instrument):
        snapshot=self.book_snapshot(instrument)
        for observer in self.book_observers:
            observer(snapshot)

    async def admit(self, trader_id, request, request_key=None):
        async with self.lock:
            if self.closing:
                raise RuntimeError('Trading service is closing')
            if request_key is not None:
                identity = await asyncio.to_thread(self.request_identities.lookup, trader_id, request_key)
                if identity:
                    return self.request_identities.verify(identity, request)
            try:
                await asyncio.to_thread(self.verify_owner)
            except Exception:
                self.dispatcher.failure = 'Matching ownership connection lost; reconciliation required'
                self.dispatcher.failure_kind = FailureKind.OWNERSHIP_LOST
                raise RuntimeError(self.dispatcher.failure) from None
            # Each resting order can cause at most one fill in this turn.
            maximum = self.engine.book.potential_fill_count(
                request.instrument_id, request.side, request.price_ticks, str(trader_id))
            self.dispatcher.check_capacity(maximum)
            if request.price_ticks > 2**53 - 1:
                raise ValueError('Price exceeds exact Redis demo range')
            try:
                row = await self.committed_io(self.database.reserve, trader_id, request, request_key)
                if row.get('_replayed'):
                    return row
            except psycopg.Error as exc:
                if exc.sqlstate not in ('P0001','22023','22003','23514','23503'):
                    self.dispatcher.failure = 'Reservation outcome uncertain; operator reconciliation required'
                raise
            except BaseException:
                # A canceled awaiting task cannot cancel a committing DB thread.
                self.dispatcher.failure = 'Reservation interrupted; operator reconciliation required'
                raise
            try:
                ids = await asyncio.to_thread(self.database.execution_ids, maximum)
                self.dispatcher.check_capacity(maximum)
                if row['id'] <= self.last_order_id:
                    raise RuntimeError('Order admission identity invariant failed')
                result = self.engine.submit(Order(row['id'], str(trader_id), row['instrument_id'], row['side'], row['price_ticks'], row['quantity']))
                self.last_order_id = row['id']
                now = datetime.now(timezone.utc)
                events = [TradeEvent.from_fill(fill, event_id=ids[i], taker_order_id=row['id'], occurred_at=now) for i, fill in enumerate(result.fills)]
                self.dispatcher.publish(events)
                self.version += 1
                if result.self_trade_prevented:
                    if self.worker is None:
                        self.dispatcher.failure = 'Self-trade residual requires terminal processing'
                    else:
                        await self.worker.drain()
                        await self.committed_io(self.database.cancel,row['id'],trader_id)
                if hasattr(self, 'live_bus'):
                    self.live_bus.publish('order.changed', trader_ids=(trader_id,), instrument_id=row['instrument_id'])
                    self.live_bus.publish('account.changed', trader_ids=(trader_id,))
                self.notify_book(row['instrument_id'])
                return row
            except BaseException:
                self.dispatcher.failure = 'Admission failed after reservation; operator reconciliation required'
                raise

    async def cancel(self, order_id, trader_id):
        async with self.lock:
            if self.closing:
                raise RuntimeError('Trading service is closing')
            if not self.worker:
                raise RuntimeError('Settlement not installed')
            await self.worker.drain()
            try:
                await asyncio.to_thread(self.verify_owner)
            except Exception:
                self.dispatcher.failure='Matching ownership lost; reconciliation required'
                self.dispatcher.failure_kind=FailureKind.OWNERSHIP_LOST
                raise RuntimeError(self.dispatcher.failure) from None
            rows = await asyncio.to_thread(self.database.query,
                'SELECT status,instrument_id FROM public."order" WHERE id=%s AND trader_id=%s UNION ALL SELECT status,instrument_id FROM order_history WHERE id=%s AND trader_id=%s',
                (order_id,trader_id,order_id,trader_id))
            if not rows:
                raise LookupError('Unknown owned order')
            if rows[0]['status']=='FILLED':
                raise ValueError('Filled order cannot be canceled')
            try:
                quantity = await self.committed_io(self.database.cancel,order_id,trader_id)
                self.engine.cancel(order_id)
            except BaseException:
                self.dispatcher.failure = 'Cancellation outcome uncertain; reconciliation required'
                raise
            self.version += 1
            if hasattr(self, 'live_bus'):
                self.live_bus.publish('order.changed', trader_ids=(trader_id,), instrument_id=rows[0]['instrument_id'])
                self.live_bus.publish('account.changed', trader_ids=(trader_id,))
            self.notify_book(rows[0]['instrument_id'])
            return quantity

    def close(self):
        self.lease.close()
