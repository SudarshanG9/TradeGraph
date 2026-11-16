"""Bounded durable polling, per-row acknowledgment and controlled retry backoff."""
import asyncio
from backend.events.durable_outbox import process_one


class OutboxWorker:
    def __init__(self, database, consumer, handler):
        self.database, self.consumer, self.handler = database, consumer, handler
        self.task = None
        self.failed = None
        self.stopping = False

    def start(self):
        self.task = asyncio.create_task(self.run())

    async def run(self):
        while not self.stopping:
            job = asyncio.create_task(asyncio.to_thread(process_one, self.database, self.consumer, self.handler))
            try:
                worked = await asyncio.shield(job)
                self.failed = None
            except asyncio.CancelledError:
                # Do not release matching ownership while a derived writer is alive.
                try:
                    await job
                except Exception:
                    pass
                raise
            except Exception:
                self.failed = 'Durable publication unavailable; retry pending'
                worked = False
            if not worked:
                await asyncio.sleep(.25 if not self.failed else 1)

    async def stop(self):
        self.stopping = True
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
