"""Crash boundaries against an explicitly isolated database; no live process kills."""
import asyncio
import os
from types import SimpleNamespace

import pytest
from backend.config import Settings
from backend.stores.postgres import Database
from backend.risk.order_reservation import Coordinator
from backend.api.routes.orders import NewOrder
from tests.integration.test_order_pipeline import accounts, order
from tests.concurrency.test_settlement_recovery import fixture_event, drive, assert_committed


@pytest.fixture(autouse=True)
def isolated_only():
    if not os.environ.get('POSTGRES_DB', '').startswith('tradegraph_test_'):
        pytest.skip('Crash tests require explicit tradegraph_test_ database')


def test_reservation_commit_without_matching_is_ambiguous(accounts):
    users, instrument = accounts
    db = Database(Settings.from_env())
    row = db.reserve(users[0]['trader_id'], NewOrder(**order(instrument)))
    assert row['status'] == 'OPEN' and row['filled_quantity'] == 0
    assert db.query('SELECT count(*) AS n FROM execution WHERE buy_order_id=%s', (row['id'],))[0]['n'] == 0
    with pytest.raises(RuntimeError, match='operator reconciliation'):
        db.acquire_owner()
    account = db.query('SELECT cash_balance,escrow_balance FROM margin_account WHERE trader_id=%s', (users[0]['trader_id'],))[0]
    assert account == {'cash_balance': 19899, 'escrow_balance': 101}


def test_matched_unsettled_fills_are_not_reconstructable_from_execution(accounts):
    users, instrument = accounts
    db = Database(Settings.from_env())
    async def run():
        service = Coordinator(db, Settings.from_env())
        try:
            await service.admit(users[0]['trader_id'], NewOrder(**order(instrument)))
            await service.admit(users[1]['trader_id'], NewOrder(**order(instrument, 'SELL')))
            assert service.dispatcher.queue.qsize() == 1
            assert service.engine.book.depth(instrument, 'BUY') == []
            assert db.query('SELECT count(*) AS n FROM execution WHERE instrument_id=%s', (instrument,))[0]['n'] == 0
            rows = db.query('SELECT status,filled_quantity FROM public."order" WHERE instrument_id=%s', (instrument,))
            assert rows == [{'status': 'OPEN', 'filled_quantity': 0}]*2
        finally:
            await service.finish_admissions()
            service.close()
    asyncio.run(run())
    with pytest.raises(RuntimeError, match='operator reconciliation'):
        db.acquire_owner()


def test_commit_survives_lost_publication_without_double_settlement(accounts):
    a, b, event = fixture_event(accounts)
    db = Database(Settings.from_env())
    def interrupted(_):
        raise RuntimeError('process lost publication progress')
    worker, dispatcher, observed = drive(db, event, [interrupted])
    assert worker.pending_committed and dispatcher.failure
    assert observed == [event]
    assert_committed(a, b, event)
    assert db.settle(event) is False
    assert_committed(a, b, event)
