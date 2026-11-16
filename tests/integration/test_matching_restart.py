"""Verified terminal restart/archival and owner exclusion; active restart stays gated."""
from datetime import datetime, timedelta, timezone
import os
import pytest
from backend.config import Settings
from backend.stores.postgres import Database
from tests.integration.test_order_pipeline import accounts
from tests.concurrency.test_settlement_recovery import fixture_event, assert_committed


@pytest.fixture(autouse=True)
def isolated_only():
    if not os.environ.get('POSTGRES_DB','').startswith('tradegraph_test_'):
        pytest.skip('Requires explicit isolated test database')


def test_terminal_commit_archival_and_second_owner_exclusion(accounts):
    a,b,event=fixture_event(accounts)
    db=Database(Settings.from_env());db.settle(event)
    archived=db.archive_terminal_orders(datetime.now(timezone.utc)+timedelta(seconds=1),100,[a['trader_id'],b['trader_id']])
    assert len(archived)==2
    owner=db.acquire_owner()
    try:
        with pytest.raises(RuntimeError,match='Another matching owner'):
            db.acquire_owner()
        assert not db.settle(event)
        assert db.query('SELECT filled_quantity FROM order_history WHERE id=ANY(%s)',([event.buy_order_id,event.sell_order_id],))==[{'filled_quantity':1}]*2
    finally:
        owner.close()
    again=db.acquire_owner();again.close()
