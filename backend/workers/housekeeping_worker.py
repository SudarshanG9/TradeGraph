"""Opt-in bounded maintenance. Failure never poisons financial settlement."""
import asyncio
from datetime import datetime,timedelta,timezone


class HousekeepingWorker:
    def __init__(self,database,settings):
        self.database,self.settings=database,settings
        self.task=None
        self.stopping=asyncio.Event()
        self.failure=None
        self.archived=0
        self.cycles=0

    def start(self):
        if self.task is not None:
            raise RuntimeError('Housekeeping already started')
        self.task=asyncio.create_task(self.run(),name='tradegraph-housekeeping')

    async def cycle(self):
        cutoff=datetime.now(timezone.utc)-timedelta(seconds=self.settings.archive_age_seconds)
        rows=await asyncio.to_thread(self.database.archive_terminal_orders,cutoff,self.settings.maintenance_batch_size)
        self.archived+=len(rows)
        self.cycles+=1
        self.failure=None

    async def wait(self,seconds):
        try: await asyncio.wait_for(self.stopping.wait(),seconds)
        except TimeoutError: pass

    async def run(self):
        while not self.stopping.is_set():
            for attempt in range(self.settings.maintenance_retries):
                try:
                    await self.cycle()
                    break
                except Exception:
                    self.failure='Maintenance unavailable; bounded retry pending'
                    if self.stopping.is_set(): break
                    await self.wait(min(2**attempt,30))
            await self.wait(self.settings.maintenance_interval_seconds)

    async def stop(self):
        self.stopping.set()
        if self.task:
            # Do not cancel a DB thread or release the owner lease before it exits.
            await asyncio.shield(self.task)
