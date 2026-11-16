"""Canonical graph and persisted regime observations survive process-local loss."""
from datetime import datetime, timedelta, timezone
import os
import pytest
from fastapi.testclient import TestClient
from backend.api.main import create_app
from backend.config import Settings
from backend.events.durable_outbox import process_one
from backend.stores.neo4j_graph import Neo4jGraph
from backend.stores.postgres import Database
from backend.stores.regimes import Regimes
from tests.integration.test_order_pipeline import accounts, login, order
from tests.integration.test_polyglot import wait_until
from tests.concurrency.test_settlement_recovery import fixture_event, assert_committed


@pytest.fixture(autouse=True)
def isolated_only():
    if not os.environ.get('POSTGRES_DB', '').startswith('tradegraph_test_'):
        pytest.skip('Requires explicit isolated test database')


def drain(db, consumer, handler):
    for _ in range(1000):
        if not process_one(db,consumer,handler):
            return
    pytest.fail('Outbox failed to drain in bounded fixture')


def test_real_graph_duplicate_delivery_and_restart_are_absolute(accounts):
    a,b,event=fixture_event(accounts)
    db=Database(Settings.from_env());db.settle(event)
    graph=Neo4jGraph(Settings.from_env(),db)
    try:
        drain(db,'graph',lambda event,payload:graph.apply(event))
        expected={'trade_count':1,'total_notional':100}
        assert graph.apply(event)==expected
        # External success / missing SQL ACK: deliberately replay on a fresh worker.
        with db.connect() as conn:
            conn.execute("UPDATE event_outbox SET completed_at=NULL WHERE execution_id=%s AND consumer='graph'",(event.event_id,))
        drain(Database(Settings.from_env()),'graph',lambda event,payload:graph.apply(event))
        assert graph.apply(event)==expected
        assert_committed(a,b,event)
    finally:
        graph.close()


def test_observation_is_atomic_and_replayed_without_current_book(accounts):
    a,b,event=fixture_event(accounts)
    db=Database(Settings.from_env())
    book={'instrument_id':event.instrument_id,'epoch':'original','version':3,'bids':[[95,3]],'asks':[[105,2]]}
    db.regime_books={event.instrument_id:book}
    assert db.settle(event)
    row=db.query("SELECT payload FROM event_outbox WHERE execution_id=%s AND consumer='regime'",(event.event_id,))[0]
    payload=row['payload']
    assert payload['book']==book and payload['features'][:2]==[.1,.2]
    recovered=Database(Settings.from_env());store=Regimes(recovered)
    drain(recovered,'regime',store.apply_observation)
    with recovered.admin_context() as conn:
        observed=conn.execute('SELECT captured_at,features::text AS features FROM regime_snapshot WHERE instrument_id=%s',(event.instrument_id,)).fetchone()
    assert observed['captured_at']==datetime.fromisoformat(payload['captured_at'])
    assert_committed(a,b,event)


def test_missing_observation_is_reported_pending_and_never_invented(accounts):
    _,_,event=fixture_event(accounts)
    db=Database(Settings.from_env());db.settle(event)
    drain(db,'regime',lambda *_:pytest.fail('historical observation was invented'))
    row=db.query("SELECT payload,completed_at FROM event_outbox WHERE execution_id=%s AND consumer='regime'",(event.event_id,))[0]
    assert row=={'payload':None,'completed_at':None}


def test_metadata_failure_rolls_back_financial_commit(accounts,monkeypatch):
    a,b,event=fixture_event(accounts)
    db=Database(Settings.from_env());db.regime_books={}
    with pytest.raises(RuntimeError,match='observation'):
        db.settle(event)
    assert db.query('SELECT id FROM execution WHERE id=%s',(event.event_id,))==[]
    assert db.query('SELECT execution_id FROM event_outbox WHERE execution_id=%s',(event.event_id,))==[]


def test_live_settlement_uses_durable_consumers_and_clean_restart(accounts):
    users,iid=accounts
    with TestClient(create_app()) as client:
        a,b=login(client,users[0]),login(client,users[1])
        assert client.post('/orders',headers=a,json=order(iid)).status_code==201
        assert client.post('/orders',headers=b,json=order(iid,'SELL')).status_code==201
        service=client.app.state.service
        wait_until(lambda:service.database.query('SELECT count(*) AS n FROM event_outbox o JOIN execution e ON e.id=o.execution_id WHERE e.instrument_id=%s AND o.completed_at IS NOT NULL',(iid,)),lambda r:r[0]['n']==2)
        assert client.get('/health').json()['trading_ready']
    with TestClient(create_app()) as recovered:
        assert recovered.app.state.replayed_executions>=1
        assert recovered.get('/health').json()['trading_ready']


def test_delayed_regime_retry_cannot_replace_newer_observation(accounts):
    _,_,first=fixture_event(accounts)
    db=Database(Settings.from_env())
    db.regime_books={first.instrument_id:{'epoch':'same','version':1,'bids':[[95,3]],'asks':[[105,2]]}}
    db.settle(first)
    # Hold the older observation while a newer canonical execution is delivered.
    with db.connect() as conn:
        conn.execute("UPDATE event_outbox SET next_attempt_at=now()+interval '1 hour' WHERE execution_id=%s AND consumer='regime'",(first.event_id,))
    _,_,second=fixture_event(accounts)
    db.regime_books[first.instrument_id]={'epoch':'same','version':2,'bids':[[80,1]],'asks':[[120,5]]}
    db.settle(second)
    store=Regimes(db)
    drain(db,'regime',store.apply_observation)
    second_payload=db.query("SELECT payload FROM event_outbox WHERE execution_id=%s AND consumer='regime'",(second.event_id,))[0]['payload']
    first_payload=db.query("SELECT payload FROM event_outbox WHERE execution_id=%s AND consumer='regime'",(first.event_id,))[0]['payload']
    if first_payload['captured_at'] != second_payload['captured_at']:
        pytest.skip('Fixture crossed a minute boundary; distinct snapshots cannot overwrite')
    with db.connect() as conn:
        conn.execute('UPDATE event_outbox SET next_attempt_at=now() WHERE execution_id=%s',(first.event_id,))
    drain(db,'regime',store.apply_observation)
    with db.admin_context() as conn:
        row=conn.execute('SELECT features::text AS features FROM regime_snapshot WHERE instrument_id=%s AND captured_at=%s',(first.instrument_id,datetime.fromisoformat(second_payload['captured_at']))).fetchone()
    import json
    assert json.loads(row['features'])==pytest.approx(second_payload['features'])


def test_delayed_replay_preserves_newer_live_regime_observation(accounts):
    import json
    _,_,event=fixture_event(accounts)
    db=Database(Settings.from_env())
    db.regime_books={event.instrument_id:{'epoch':'same','version':1,'bids':[[95,3]],'asks':[[105,2]]}}
    db.settle(event)
    payload=db.query("SELECT payload FROM event_outbox WHERE execution_id=%s AND consumer='regime'",(event.event_id,))[0]['payload']
    store=Regimes(db)
    # Admin/current capture is a newer real observation in the same minute bucket.
    newer_features=[.4,-.5,0,.1,.25,0]
    store.upsert(event.instrument_id,datetime.fromisoformat(payload['captured_at']),newer_features)
    drain(db,'regime',store.apply_observation)
    with db.admin_context() as conn:
        actual=conn.execute('SELECT features::text AS features FROM regime_snapshot WHERE instrument_id=%s AND captured_at=%s',
                            (event.instrument_id,datetime.fromisoformat(payload['captured_at']))).fetchone()
    assert json.loads(actual['features'])==pytest.approx(newer_features)


def test_unknown_historical_observation_is_preserved_and_replay_stays_pending(accounts):
    _,_,event=fixture_event(accounts)
    db=Database(Settings.from_env())
    db.regime_books={event.instrument_id:{'epoch':'same','version':1,'bids':[[95,3]],'asks':[[105,2]]}}
    db.settle(event)
    payload=db.query("SELECT payload FROM event_outbox WHERE execution_id=%s AND consumer='regime'",(event.event_id,))[0]['payload']
    store=Regimes(db)
    captured=datetime.fromisoformat(payload['captured_at'])
    store.upsert(event.instrument_id,captured,[1,0,0,0,0,0])
    with db.admin_context() as conn:
        # Model an existing pre-migration snapshot: no invented timestamp backfill.
        conn.execute('UPDATE regime_snapshot SET observed_at=NULL,observation_execution_id=NULL WHERE instrument_id=%s',(event.instrument_id,))
    drain(db,'regime',store.apply_observation)
    row=db.query("SELECT last_error,completed_at FROM event_outbox WHERE execution_id=%s AND consumer='regime'",(event.event_id,))[0]
    assert row['last_error']=='ObservationOrderUnknown' and row['completed_at'] is None
    with db.admin_context() as conn:
        row=conn.execute('SELECT features::text AS features,observed_at FROM regime_snapshot WHERE instrument_id=%s',(event.instrument_id,)).fetchone()
    assert row=={'features':'[1,0,0,0,0,0]','observed_at':None}
