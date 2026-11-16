"""Proven service grants; this shared login is not a database tenant boundary."""
import pytest
from psycopg.errors import InsufficientPrivilege
from backend.config import Settings
from backend.stores.postgres import Database
from scripts.verify_schema import db_connect
from tests.integration.test_order_pipeline import accounts


@pytest.mark.parametrize('table', ['margin_account','order','order_history','position','execution','user_account','trader'])
def test_runtime_cannot_directly_modify_financial_or_identity_rows(table):
    db=Database(Settings.from_env())
    with db.connect() as conn:
        with pytest.raises(InsufficientPrivilege):
            conn.execute(f'DELETE FROM public."{table}" WHERE false')


def test_narrow_identity_columns_and_transaction_role_do_not_leak():
    db=Database(Settings.from_env())
    assert db.auth_query('SELECT id,role,password_hash FROM user_account LIMIT 1')
    if db.settings.database_identity_mode=='isolated':
        with db.connect() as conn:
            with pytest.raises(InsufficientPrivilege):conn.execute('SELECT password_hash FROM user_account')
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


def test_trader_logins_enforce_financial_row_isolation_despite_forged_context(accounts):
    from tests.concurrency.test_settlement_locks import reserve,make_event
    from backend.api.routes.orders import NewOrder
    from datetime import datetime,timedelta,timezone
    users,instrument=accounts;a,b=users[:2];db=Database(Settings.from_env())
    assert db.settings.database_identity_mode=='isolated', 'Run this boundary proof with approved isolated credentials'
    buy=reserve(a,instrument,'BUY',100,2);sell=reserve(b,instrument,'SELL',100,1)
    db.settle(make_event(buy,sell,a,b,instrument,100,1))
    db.archive_terminal_orders(datetime.now(timezone.utc)+timedelta(days=1),100,[b['trader_id']])
    for user in (a,b):
        db.reserve(user['trader_id'],NewOrder(instrument_id=instrument,side='BUY',price_ticks=1,quantity=1),'owned-identity')
    for owner,other in ((a,b),(b,a)):
        with db.trader_context(owner['trader_id']) as conn:
            for table in ('margin_account','order','order_history','position','order_request_identity'):
                rows=conn.execute(f'SELECT trader_id FROM public."{table}"').fetchall()
                assert all(r['trader_id']==owner['trader_id'] for r in rows)
                assert not conn.execute(f'SELECT trader_id FROM public."{table}" WHERE trader_id=%s',(other['trader_id'],)).fetchall()
            conn.execute("SELECT set_config('app.trader_id',%s,true)",(str(other['trader_id']),))
            conn.execute("SET LOCAL app.role='COMPLIANCE_ADMIN'")
            assert [r['trader_id'] for r in conn.execute('SELECT trader_id FROM margin_account')]==[owner['trader_id']]
            for statement in ('SET LOCAL ROLE compliance_admin_role',
                              'SELECT public.cancel_order(1,\'00000000-0000-0000-0000-000000000001\'::uuid)',
                              'SET SESSION AUTHORIZATION compliance_admin_role'):
                with pytest.raises(InsufficientPrivilege):
                    with conn.transaction():conn.execute(statement)
            from psycopg.errors import ReadOnlySqlTransaction
            assert not conn.execute("SELECT has_table_privilege(current_user,'margin_account','DELETE') AS allowed").fetchone()['allowed']
            with pytest.raises(ReadOnlySqlTransaction):
                with conn.transaction():conn.execute('DELETE FROM margin_account WHERE false')
        # A fresh connection uses its actual login; no GUC/SET ROLE leaks.
        assert db.trader_query(owner['trader_id'],'SELECT current_setting(\'app.trader_id\',true) AS value')[0]['value'] is None
    with db.connect() as conn:
        conn.execute('SET LOCAL ROLE trader_role')
        conn.execute("SELECT set_config('app.trader_id',%s,true)",(str(a['trader_id']),))
        assert conn.execute('SELECT * FROM margin_account').fetchall()==[]
    with db.connect() as conn:
        with pytest.raises(InsufficientPrivilege):conn.execute('SET LOCAL ROLE compliance_admin_role')
    with db.admin_context() as conn:
        rows=conn.execute('SELECT trader_id FROM margin_account WHERE trader_id=ANY(%s)',([a['trader_id'],b['trader_id']],)).fetchall()
        assert len(rows)==2
        with pytest.raises(InsufficientPrivilege):
            with conn.transaction():conn.execute('DELETE FROM margin_account WHERE false')
    with pytest.raises(InsufficientPrivilege):db.auth_query('SELECT * FROM margin_account')


def test_scram_authenticates_real_trader_and_rejects_wrong_password(accounts):
    from backend.stores.trader_identity import credentials
    users,_=accounts;db=Database(Settings.from_env())
    user,password=credentials(db.settings.trader_credentials_file,users[0]['trader_id'])
    import psycopg
    with pytest.raises(psycopg.OperationalError):db._connect_as(user,'incorrect-isolated-test-password')
    with db._connect_as(user,password) as conn:
        assert conn.execute('SELECT session_user AS user').fetchone()['user']==user


def test_startup_rejects_auth_login_used_as_financial_identity():
    from dataclasses import replace
    settings=Settings.from_env()
    wrong=Database(replace(settings,postgres_runtime_user=settings.postgres_auth_user,
                           postgres_runtime_password=settings.postgres_auth_password))
    with pytest.raises(RuntimeError,match='boundary'):wrong.acquire_owner()
