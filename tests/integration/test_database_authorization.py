"""Proven service grants; this shared login is not a database tenant boundary."""
import pytest
from psycopg.errors import InsufficientPrivilege
from backend.config import Settings
from backend.stores.postgres import Database
from scripts.verify_schema import db_connect


@pytest.mark.parametrize('table', ['margin_account','order','order_history','position','execution','user_account','trader'])
def test_runtime_cannot_directly_modify_financial_or_identity_rows(table):
    db=Database(Settings.from_env())
    with db.connect() as conn:
        with pytest.raises(InsufficientPrivilege):
            conn.execute(f'DELETE FROM public."{table}" WHERE false')


def test_narrow_identity_columns_and_transaction_role_do_not_leak():
    db=Database(Settings.from_env())
    assert db.query('SELECT id,role,password_hash FROM user_account LIMIT 1')
    with db.connect() as conn:
        with pytest.raises(InsufficientPrivilege): conn.execute('SELECT created_at FROM user_account')
    with db.admin_context() as conn:
        assert conn.execute('SELECT current_user AS name').fetchone()['name']=='compliance_admin_role'
        conn.execute('SELECT * FROM market_disclosure LIMIT 0')
    with db.connect() as conn:
        assert conn.execute('SELECT current_user AS name').fetchone()['name']==Settings.from_env().postgres_runtime_user
        assert conn.execute("SELECT current_setting('app.role',true) AS role").fetchone()['role'] is None
        with pytest.raises(InsufficientPrivilege): conn.execute('SELECT * FROM market_disclosure')


def test_generic_roles_cannot_execute_unbound_financial_functions(db_conn):
    for role in ('trader_role','compliance_admin_role'):
        for signature in ('public.place_and_reserve_order(uuid,integer,text,bigint,bigint)',
                          'public.cancel_order(bigint,uuid)',
                          'public.settle_execution(bigint,integer,bigint,bigint,uuid,uuid,bigint,bigint,bigint,timestamptz)'):
            assert not db_conn.execute('SELECT has_function_privilege(%s,%s,\'EXECUTE\')',(role,signature)).fetchone()[0]
