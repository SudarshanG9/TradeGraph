"""Bounded in-process handoff; intentionally no durable outbox."""
import asyncio
from enum import Enum


class FailureKind(str, Enum):
    DERIVED_BACKLOG_FULL = "DERIVED_BACKLOG_FULL"
    POST_COMMIT = "POST_COMMIT"
    FINANCIAL_UNCERTAIN = "FINANCIAL_OUTCOME_UNCERTAIN"
    OWNERSHIP_LOST = "OWNERSHIP_LOST"


class PipelineFull(RuntimeError):
    pass



class Dispatcher:
    def __init__(self, capacity):
        self.queue = asyncio.Queue(capacity)
        self.failure = None
        self.failure_kind = None

    def check_capacity(self, count):
        if self.failure:
            raise RuntimeError('Event pipeline unhealthy or full')
        if count > self.queue.maxsize - self.queue.qsize():
            raise PipelineFull('Event pipeline full')

    def publish(self, events):
        for event in events:
            self.queue.put_nowait(event)


class DerivedWorker:
    """Bounded post-commit jobs with retained retry; overflow fails admissions closed."""
    def __init__(self, name, handler, dispatcher):
        self.name,self.handler,self.dispatcher=name,handler,dispatcher
        self.queue=asyncio.Queue(dispatcher.queue.maxsize)
        self.task=None
        self.pending=None
        self.failed=None

    def start(self):
        self.task=asyncio.create_task(self.run())

    def publish(self,payload):
        try:
            self.queue.put_nowait(payload)
        except asyncio.QueueFull:
            self.dispatcher.failure=f'{self.name} backlog full; reconciliation required'
            self.dispatcher.failure_kind=FailureKind.DERIVED_BACKLOG_FULL
            raise RuntimeError(self.dispatcher.failure) from None

    async def run(self):
        while True:
            payload=await self.queue.get()
            self.pending=payload
            try:
                while True:
                    job=asyncio.create_task(asyncio.to_thread(self.handler,payload))
                    try:
                        await asyncio.shield(job)
                        self.failed=None
                        self.pending=None
                        break
                    except asyncio.CancelledError:
                        # Do not release ownership while an old cache writer is in flight.
                        try: await job
                        except Exception: pass
                        raise
                    except Exception:
                        self.failed=f'{self.name} unavailable; retry pending'
                        await asyncio.sleep(0.1)
            finally:
                self.queue.task_done()

    async def stop(self):
        try: await asyncio.wait_for(self.queue.join(),timeout=5)
        except TimeoutError: pass
        if self.task:
            self.task.cancel()
            try: await self.task
            except asyncio.CancelledError: pass
