"""Diagnostics are read-only; health cannot perform reconciliation or clear failures."""
import os
import pytest
from fastapi.testclient import TestClient
from backend.api.main import create_app
from backend.config import Settings
from backend.stores.postgres import Database
from scripts.reconcile_restart import diagnose
from tests.integration.test_order_pipeline import accounts, login, order
from tests.concurrency.test_settlement_recovery import fixture_event


@pytest.fixture(autouse=True)
def isolated_only():
    if not os.environ.get('POSTGRES_DB','').startswith('tradegraph_test_'):
        pytest.skip('Requires explicit isolated test database')


def test_diagnose_reports_pending_legacy_observation_and_exact_financial_state(accounts):
    _,_,event=fixture_event(accounts)
    db=Database(Settings.from_env());db.settle(event)
    before=db.query('SELECT * FROM event_outbox WHERE execution_id=%s ORDER BY consumer',(event.event_id,))
    result=diagnose(db)
    assert result['mode']=='read_only' and result['durable_publication_installed']
    assert result['outbox_pending']>=2 and result['historical_observations_missing']>=1
    assert not any(result[k] for k in ('volume_mismatches','position_mismatches','escrow_mismatches','duplicate_order_ids','execution_order_mismatches'))
    assert db.query('SELECT * FROM event_outbox WHERE execution_id=%s ORDER BY consumer',(event.event_id,))==before


def test_active_diagnostic_and_health_never_clear_failures_or_orders(accounts):
    users,iid=accounts
    with TestClient(create_app()) as client:
        response=client.post('/orders',headers=login(client,users[0]),json=order(iid))
        assert response.status_code==201
        service=client.app.state.service
        service.dispatcher.failure='operator reconciliation required'
        result=diagnose(service.database)
        assert not result['cold_start_safe'] and result['active_orders']==1
        assert result['matching_owner_locks']==1
        assert 'unknown' in result['pending_financial_operations']
        for _ in range(2):
            health=client.get('/health').json()
            assert not health['trading_ready'] and health['readiness']['reconciliation_required']
        assert service.dispatcher.failure=='operator reconciliation required'
        assert service.database.query('SELECT status FROM public."order" WHERE id=%s',(response.json()['order_id'],))[0]['status']=='OPEN'
