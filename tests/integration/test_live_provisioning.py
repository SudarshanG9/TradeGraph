"""Native provisioning checks, entirely rolled back by db_conn."""
import pytest
from scripts.seed_live_bots import load_bot_specs, inspect_existing_bots, provision_missing_bots
from scripts.verify_schema import EXPECTED_TABLES


def test_allowlist_and_dry_inspection(db_conn):
    specs = load_bot_specs()
    assert len(specs) == len({s.email for s in specs}) == 8
    assert all(s.email.startswith('sim-live-') and s.email.endswith('@tradegraph.test') for s in specs)
    before = db_conn.execute('SELECT count(*) FROM user_account').fetchone()
    rows = inspect_existing_bots(db_conn, specs)
    assert len(rows) == 8
    assert db_conn.execute('SELECT count(*) FROM user_account').fetchone() == before
    assert 'password' not in repr(rows)
    with pytest.raises(ValueError):
        inspect_existing_bots(db_conn, specs[:1])


def test_apply_idempotent_preserves_all_existing_state(db_conn):
    specs = load_bot_specs()
    original = db_conn.execute('SELECT * FROM user_account ORDER BY id').fetchall()
    result = provision_missing_bots(db_conn, specs, 10000)
    assert all(result.values())
    before = db_conn.execute('SELECT * FROM margin_account ORDER BY trader_id').fetchall()
    credentials = db_conn.execute('SELECT id,password_hash FROM user_account ORDER BY id').fetchall()
    assert all(r[1].startswith(('$2a$', '$2b$')) for r in credentials)
    assert provision_missing_bots(db_conn, specs, 99999) == result
    assert before == db_conn.execute('SELECT * FROM margin_account ORDER BY trader_id').fetchall()
    assert credentials == db_conn.execute('SELECT id,password_hash FROM user_account ORDER BY id').fetchall()
    assert all(row in db_conn.execute('SELECT * FROM user_account').fetchall() for row in original)
    assert {r[0] for r in db_conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")} == EXPECTED_TABLES


@pytest.mark.parametrize('conflict', ['role', 'name', 'kyc', 'margin'])
def test_partial_and_conflicting_identities_rejected(db_conn, conflict):
    specs = load_bot_specs()
    rows = provision_missing_bots(db_conn, specs)
    row = rows[specs[0].email]
    if conflict == 'role':
        db_conn.execute("UPDATE user_account SET role='COMPLIANCE_ADMIN' WHERE id=%s", (row['user_id'],))
    elif conflict == 'name':
        db_conn.execute("UPDATE trader SET full_name='Ordinary user' WHERE id=%s", (row['trader_id'],))
    elif conflict == 'kyc':
        db_conn.execute('DELETE FROM kyc_profile WHERE trader_id=%s', (row['trader_id'],))
    else:
        db_conn.execute('DELETE FROM margin_account WHERE trader_id=%s', (row['trader_id'],))
    with pytest.raises(ValueError, match='Conflicting or incomplete'):
        provision_missing_bots(db_conn, specs)


@pytest.mark.parametrize('cash', [0, -1, 100000001, True])
def test_funding_bounds(db_conn, cash):
    with pytest.raises(ValueError):
        provision_missing_bots(db_conn, load_bot_specs(), cash)
