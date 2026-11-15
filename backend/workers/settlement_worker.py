"""Single financial consumer; no downstream side effect before PostgreSQL commit."""
import asyncio
import psycopg
from backend.clearing.settlement import settle


class SettlementWorker:
    def __init__(self, database, engine, dispatcher):
        self.database, self.engine, self.dispatcher = database, engine, dispatcher
        self.pending = None
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
            try:
                for attempt in range(3):
                    try:
                        await asyncio.to_thread(settle, self.database, event)
                        break
                    except psycopg.Error as exc:
                        if attempt==2 or exc.sqlstate not in (None,'40001','40P01'):
                            raise
                        await asyncio.sleep(0.01 * (attempt+1))
                self.engine.apply_settled(event)
                for consumer in self.after_commit:
                    consumer(event)  # nonblocking handoffs only
                self.pending = None
            except asyncio.CancelledError:
                self.dispatcher.failure = 'Settlement interrupted; operator reconciliation required'
                raise
            except Exception:
                self.dispatcher.failure = 'Settlement failed; immutable pending event retained for reconciliation'
                return  # pending retains the event; never acknowledge financial success
            finally:
                self.dispatcher.queue.task_done()

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
