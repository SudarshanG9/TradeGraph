"""Global admission serialization includes reservation and PostgreSQL COMMIT."""
import asyncio
import psycopg
from datetime import datetime, timezone
from uuid import uuid4
from backend.events.dispatcher import Dispatcher
from backend.events.trade_event import TradeEvent
from backend.matching.engine import Engine
from backend.matching.order_book import Order


class Coordinator:
    def __init__(self, database, settings):
        self.database = database
        self.settings = settings
        self.engine = Engine()
        self.lock = asyncio.Lock()
        self.dispatcher = Dispatcher(settings.event_queue_capacity)
        self.lease = database.acquire_owner()
        self.last_order_id = 0
        self.version = 0
        self.worker = None
        self.book_observers = []
        self.derived = {}
        self.epoch = str(uuid4())

    def notify_book(self, instrument):
        snapshot={'instrument_id':instrument,'version':self.version,'epoch':self.epoch,
                  'as_of':datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
                  'bids':self.engine.book.depth(instrument,'BUY'),
                  'asks':self.engine.book.depth(instrument,'SELL')}
        for observer in self.book_observers:
            observer(snapshot)

    async def admit(self, trader_id, request):
        async with self.lock:
            try:
                await asyncio.to_thread(self.lease.execute, 'SELECT 1')
            except Exception:
                self.dispatcher.failure = 'Matching ownership connection lost; reconciliation required'
                raise RuntimeError(self.dispatcher.failure) from None
            # Each resting order can cause at most one fill in this turn.
            maximum = len(self.engine.book._by_id)
            self.dispatcher.check_capacity(maximum)
            if request.price_ticks > 2**53 - 1:
                raise ValueError('Price exceeds exact Redis demo range')
            try:
                row = await asyncio.to_thread(self.database.reserve, trader_id, request)
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
                        await asyncio.to_thread(self.database.cancel,row['id'],trader_id)
                self.notify_book(row['instrument_id'])
                return row
            except BaseException:
                self.dispatcher.failure = 'Admission failed after reservation; operator reconciliation required'
                raise

    async def cancel(self, order_id, trader_id):
        async with self.lock:
            if not self.worker:
                raise RuntimeError('Settlement not installed')
            await self.worker.drain()
            rows = await asyncio.to_thread(self.database.query,
                'SELECT status,instrument_id FROM public."order" WHERE id=%s AND trader_id=%s UNION ALL SELECT status,instrument_id FROM order_history WHERE id=%s AND trader_id=%s',
                (order_id,trader_id,order_id,trader_id))
            if not rows:
                raise LookupError('Unknown owned order')
            if rows[0]['status']=='FILLED':
                raise ValueError('Filled order cannot be canceled')
            try:
                quantity = await asyncio.to_thread(self.database.cancel,order_id,trader_id)
                self.engine.cancel(order_id)
            except BaseException:
                self.dispatcher.failure = 'Cancellation outcome uncertain; reconciliation required'
                raise
            self.version += 1
            self.notify_book(rows[0]['instrument_id'])
            return quantity

    def close(self):
        self.lease.close()
