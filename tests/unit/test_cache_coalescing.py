import asyncio
from types import SimpleNamespace
from backend.events.dispatcher import Dispatcher
from backend.workers.cache_worker import CacheWorker


def test_replaceable_cache_backlog_coalesces_without_stale_overwrite():
    async def run():
        applied=[]
        db=SimpleNamespace(query=lambda *args:[{'symbol':'TEST'}])
        store=SimpleNamespace(apply=lambda *args,**kwargs:applied.append(kwargs['version']))
        dispatcher=Dispatcher(1);worker=CacheWorker(db,store,dispatcher)
        for version in (1,3,2,4):
            worker.publish(dict(instrument_id=1,version=version,epoch='same',as_of='test',bids=[],asks=[]))
        assert worker.queue.qsize()==1 and not dispatcher.failure
        worker.start();await worker.queue.join();await worker.stop()
        assert applied==[4]
    asyncio.run(run())
