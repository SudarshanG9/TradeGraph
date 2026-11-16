"""Atomic settlement/publication and concurrent claims in an isolated SQL cluster."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import os

import psycopg
import pytest
from backend.config import Settings
from backend.events.durable_outbox import process_one
from backend.stores.postgres import Database
from tests.integration.test_order_pipeline import accounts
from tests.concurrency.test_settlement_recovery import fixture_event, assert_committed


@pytest.fixture(autouse=True)
def isolated_only():
    if not os.environ.get('POSTGRES_DB', '').startswith('tradegraph_test_'):
        pytest.skip('Requires explicit isolated test database')


def intents(db, event):
    return db.query('SELECT * FROM event_outbox WHERE execution_id=%s ORDER BY consumer', (event.event_id,))


def test_settlement_intent_is_atomic_and_duplicate_identity_cannot_resettle(accounts):
    a, b, event = fixture_event(accounts)
    db = Database(Settings.from_env())
    assert db.settle(event)
    assert [r['consumer'] for r in intents(db, event)] == ['graph', 'regime']
    assert not db.settle(event)
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.settle(replace(event, quantity=2))
    assert len(intents(db, event)) == 2
    assert_committed(a, b, event)


def test_rollback_discards_execution_positions_and_intent(accounts):
    a, b, e = fixture_event(accounts)
    db = Database(Settings.from_env())
    with pytest.raises(RuntimeError):
        with db.connect() as conn:
            conn.execute('SELECT public.settle_execution(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                (e.event_id,e.instrument_id,e.buy_order_id,e.sell_order_id,e.buy_trader_id,e.sell_trader_id,e.price_ticks,e.quantity,e.taker_order_id,e.occurred_at))
            assert len(conn.execute('SELECT * FROM event_outbox WHERE execution_id=%s', (e.event_id,)).fetchall()) == 2
            raise RuntimeError('crash before COMMIT')
    assert intents(db, e) == []
    assert not db.query('SELECT id FROM execution WHERE id=%s', (e.event_id,))


def test_crash_after_commit_replays_without_a_settlement_worker(accounts):
    a, b, event = fixture_event(accounts)
    db = Database(Settings.from_env())
    db.settle(event)
    # Simulate total loss of process-local publication state. New DB instance only.
    recovered = Database(Settings.from_env())
    delivered = []
    for _ in range(1000):
        if not process_one(recovered, 'graph', lambda e, _: delivered.append(e)):
            break
    assert event in delivered
    assert not process_one(recovered, 'graph', lambda *_: pytest.fail('duplicate'))
    assert_committed(a, b, event)


def test_consumer_failure_is_durable_and_retryable(accounts):
    _, _, event = fixture_event(accounts)
    db = Database(Settings.from_env()); db.settle(event)
    def fail(*_):
        raise ConnectionError('private details must not be retained')
    # Drain older graph records so this fixture is the next claim.
    while process_one(db, 'graph', lambda *_: None):
        if intents(db,event)[0]['completed_at']:
            break
    with db.connect() as conn:
        conn.execute('UPDATE event_outbox SET completed_at=NULL WHERE execution_id=%s AND consumer=\'graph\'', (event.event_id,))
    assert process_one(db, 'graph', fail)
    row = intents(db, event)[0]
    assert row['completed_at'] is None and row['last_error'] == 'ConnectionError'
    assert not process_one(db, 'graph', fail)  # backoff persisted
    with db.connect() as conn:
        conn.execute('UPDATE event_outbox SET next_attempt_at=now() WHERE execution_id=%s', (event.event_id,))
    assert process_one(Database(Settings.from_env()), 'graph', lambda *_: None)
    assert intents(db, event)[0]['completed_at'] is not None


def test_concurrent_claims_do_not_deliver_same_row_twice(accounts):
    _, _, event = fixture_event(accounts)
    db = Database(Settings.from_env()); db.settle(event)
    delivered = []
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda _: process_one(db, 'graph', lambda e, _: delivered.append(e.event_id)), range(16)))
    assert delivered.count(event.event_id) == 1


def test_outbox_not_exposed_to_trader_role(accounts):
    db = Database(Settings.from_env())
    with db.connect() as conn:
        conn.execute('SET LOCAL ROLE trader_role')
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute('SELECT * FROM event_outbox')
