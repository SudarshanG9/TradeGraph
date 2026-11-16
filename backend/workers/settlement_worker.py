"""Single financial consumer; no downstream side effect before PostgreSQL commit."""
import asyncio
import psycopg
from backend.clearing.settlement import settle
from backend.events.dispatcher import FailureKind, DerivedWorker


class SettlementWorker:
    def __init__(self, database, engine, dispatcher):
        self.database, self.engine, self.dispatcher = database, engine, dispatcher
        self.pending = None
        self.pending_committed = False
        self.pending_analytics_applied = False
        self.pending_published = set()
        self.pending_consumers = ()
        self.task = None
        self.after_commit = []

    def start(self):
        self.task = asyncio.create_task(self.run())

    async def drain(self):
        if self.dispatcher.failure:
            raise RuntimeError(self.dispatcher.failure)
        joined = asyncio.create_task(self.dispatcher.queue.join())
        try:
            done, _ = await asyncio.wait((joined,self.task),timeout=30,return_when=asyncio.FIRST_COMPLETED)
            if joined not in done:
                self.dispatcher.failure = self.dispatcher.failure or 'Settlement drain failed; reconciliation required'
                raise RuntimeError(self.dispatcher.failure)
        finally:
            if not joined.done():
                joined.cancel()
                try:
                    await joined
                except asyncio.CancelledError:
                    pass
        if self.dispatcher.failure:
            raise RuntimeError(self.dispatcher.failure)

    async def run(self):
        while True:
            event = await self.dispatcher.queue.get()
            self.pending = event
            self.pending_committed = False
            self.pending_analytics_applied = False
            self.pending_published = set()
            self.pending_consumers = tuple(self.after_commit)
            try:
                for attempt in range(3):
                    try:
                        job=asyncio.create_task(asyncio.to_thread(settle,self.database,event))
                        try:
                            await asyncio.shield(job)
                        except asyncio.CancelledError:
                            # A committing DB thread cannot be canceled. Keep the
                            # owner lease until its outcome is known at shutdown.
                            try: await job
                            except Exception: pass
                            raise
                        break
                    except psycopg.Error as exc:
                        # Server transaction-abort errors leave settle()'s connection
                        # context rolled back. Connection failures may hide COMMIT.
                        if exc.sqlstate is None or (exc.sqlstate or '').startswith('08') or exc.sqlstate in ('57P01','57P02','57P03'):
                            await asyncio.to_thread(self.database.reconcile_execution,event)
                            break
                        if attempt==2 or exc.sqlstate not in ('40001','40P01','57014','55P03'):
                            raise
                        await asyncio.sleep(0.01 * (attempt+1))
                self.pending_committed = True
                self.engine.apply_settled(event)
                self.pending_analytics_applied = True
                publication_failed = False
                for index, consumer in enumerate(self.pending_consumers):
                    try:
                        consumer(event)  # nonblocking handoffs only
                        self.pending_published.add(index)
                    except Exception:
                        # Attempt the remaining independent consumers too. Retain
                        # the canonical event and stop admissions; never resettle.
                        publication_failed = True
                if publication_failed:
                    self.dispatcher.failure = 'Settlement committed; downstream publication failed; pending event retained for reconciliation'
                    self.dispatcher.failure_kind = FailureKind.POST_COMMIT
                    return
                self.pending = None
                self.pending_committed = False
            except asyncio.CancelledError:
                self.dispatcher.failure = 'Settlement interrupted; operator reconciliation required'
                raise
            except Exception:
                self.dispatcher.failure_kind = FailureKind.POST_COMMIT if self.pending_committed else FailureKind.FINANCIAL_UNCERTAIN
                self.dispatcher.failure = (
                    'Settlement committed; post-commit processing failed; pending event retained for reconciliation'
                    if self.pending_committed else
                    'Settlement failed; immutable pending event retained for reconciliation')
                return  # pending retains the event; never acknowledge financial success
            finally:
                self.dispatcher.queue.task_done()

    async def recover_committed(self, coordinator):
        """Operator/internal recovery for a retained live-process publication only.

        Never clears financial ambiguity, retries arbitrary callbacks, or claims
        crash durability. The stopped task has awaited its DB thread before exit.
        """
        async with coordinator.lock:
            if (coordinator.closing or not self.task or not self.task.done() or
                self.pending is None or not self.pending_committed or
                not self.pending_analytics_applied or
                self.dispatcher.failure_kind != FailureKind.POST_COMMIT):
                raise RuntimeError('Recovery requires a verified retained committed event')
            event = self.pending
            await asyncio.to_thread(coordinator.verify_owner)
            await asyncio.to_thread(self.database.reconcile_execution, event)
            if not self.engine.has_settled(event):
                raise RuntimeError('Analytics reconciliation required')
            if tuple(self.after_commit) != self.pending_consumers:
                raise RuntimeError('Publication configuration changed')
            for consumer in coordinator.derived.values():
                if consumer.failed or not getattr(consumer, 'ready', True):
                    raise RuntimeError('Derived consumer not ready')
            for index, callback in enumerate(self.pending_consumers):
                if index in self.pending_published:
                    continue
                target = getattr(callback, '__self__', None)
                from backend.workers.regime_worker import RegimeWorker
                known = isinstance(target, DerivedWorker) and (callback == target.publish or (isinstance(target, RegimeWorker) and callback == target.publish_settled))
                if not known or target.dispatcher is not self.dispatcher:
                    raise RuntimeError('Unverified publication callback')
                if target.queue.full():
                    raise RuntimeError('Derived backlog still full')
                callback(event)
                self.pending_published.add(index)
            # Only known atomic enqueue callbacks succeeded; no financial replay.
            self.pending = None
            self.pending_committed = False
            self.pending_analytics_applied = False
            self.dispatcher.failure = None
            self.dispatcher.failure_kind = None
            self.start()
            return True

    async def stop(self):
        if not self.dispatcher.failure:
            try:
                await self.drain()
            except Exception:
                self.dispatcher.failure = 'Shutdown could not drain settlement; reconciliation required'
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
