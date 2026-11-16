import asyncio
from types import SimpleNamespace
from backend.workers.housekeeping_worker import HousekeepingWorker


def test_housekeeping_failure_retries_without_financial_failure_and_shutdown_waits():
    async def run():
        calls=[]
        def archive(cutoff,batch):
            calls.append(batch)
            if len(calls)==1: raise RuntimeError('temporary database failure')
            return [1]
        settings=SimpleNamespace(archive_age_seconds=86400,maintenance_batch_size=2,
                                 maintenance_retries=3,maintenance_interval_seconds=60)
        worker=HousekeepingWorker(SimpleNamespace(archive_terminal_orders=archive),settings)
        async def wait(_):
            if worker.cycles: worker.stopping.set()
            await asyncio.sleep(0)
        worker.wait=wait
        worker.start();await worker.task;await worker.stop()
        assert calls==[2,2] and worker.archived==1 and worker.failure is None
    asyncio.run(run())


def test_retention_configuration_is_disabled_and_requires_explicit_instrument_scope():
    from backend.config import Settings
    from tests.unit.test_matching import configured_env
    import pytest
    assert Settings.from_env(configured_env()).regime_retention_seconds==0
    for extra in ({'REGIME_RETENTION_SECONDS':'86400'}, {'REGIME_RETENTION_SECONDS':'1','REGIME_RETENTION_INSTRUMENT_IDS':'1'},
                  {'REGIME_RETENTION_SECONDS':'86400','REGIME_RETENTION_INSTRUMENT_IDS':'1,1'}, {'MAINTENANCE_BATCH_SIZE':'0'}):
        with pytest.raises(ValueError):Settings.from_env(configured_env()|extra)
    settings=Settings.from_env(configured_env()|{'REGIME_RETENTION_SECONDS':'86400','REGIME_RETENTION_INSTRUMENT_IDS':'1,2'})
    assert settings.regime_retention_instruments==(1,2)
