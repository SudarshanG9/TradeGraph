"""Run only with additive registration migration and isolated test identities."""
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import bcrypt
import psycopg
import pytest
from backend.config import Settings
from backend.stores.postgres import Database
from backend.stores.registration import Registration, register_account
from scripts.verify_schema import db_connect


@pytest.fixture
def registrations():
    emails = []
    def create(email=None):
        email = email or f'registration-{uuid4().hex}@example.test'
        if email.lower().strip() not in emails: emails.append(email.lower().strip())
        body = Registration(full_name='New Trader', email=email, password='synthetic-registration-password')
        return register_account(Database(Settings.from_env()), body)
    yield create
    with db_connect() as conn:
        for email in emails:
            row=conn.execute('SELECT id FROM user_account WHERE lower(btrim(email))=%s',(email,)).fetchone()
            if not row:continue
            conn.execute('DELETE FROM registration_state WHERE user_account_id=%s',row)
            conn.execute('DELETE FROM margin_account WHERE trader_id IN (SELECT id FROM trader WHERE user_account_id=%s)',row)
            conn.execute('DELETE FROM trader WHERE user_account_id=%s',row)
            conn.execute('DELETE FROM user_account WHERE id=%s',row)


def test_twenty_atomic_accounts(registrations):
    results=list(ThreadPoolExecutor(8).map(lambda _:registrations(),range(20)))
    assert len({r['registration_id'] for r in results})==20
    with db_connect() as conn:
        for receipt in results:
            row=conn.execute('''SELECT u.role,u.password_hash,m.cash_balance,m.escrow_balance,f.tier_name,
               k.verified,r.status FROM user_account u JOIN trader t ON t.user_account_id=u.id
               JOIN margin_account m ON m.trader_id=t.id JOIN fee_tier f ON f.id=m.fee_tier_id
               JOIN registration_state r ON r.user_account_id=u.id LEFT JOIN kyc_profile k ON k.trader_id=t.id
               WHERE u.id=%s''',(receipt['registration_id'],)).fetchone()
            assert row[0]=='TRADER' and bcrypt.checkpw(b'synthetic-registration-password',row[1].encode())
            policy=conn.execute('SELECT initial_cash,synthetic_demo FROM registration_policy').fetchone()
            assert row[2:6]==(policy[0],0,'STANDARD',None)
            assert row[6]==('PENDING_PROVISIONING' if policy[1] else 'PENDING_VERIFICATION')


def test_concurrent_normalized_duplicate(registrations):
    email=f'duplicate-{uuid4().hex}@example.test'
    def attempt(value):
        try: return registrations(value)
        except psycopg.errors.UniqueViolation:return None
    with ThreadPoolExecutor(2) as pool:
        results=list(pool.map(attempt,[email,' '+email.upper()+' ']))
    assert sum(r is not None for r in results)==1


def test_transaction_rolls_back_after_required_insert_failure(registrations):
    # Inject only for this exact, fresh fixture name. Remove trigger in finally.
    with db_connect() as conn:
        conn.execute("""CREATE FUNCTION public.test_registration_failure() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN IF NEW.full_name='Fail Registration Fixture' THEN RAISE EXCEPTION 'fixture failure'; END IF; RETURN NEW; END $$""")
        conn.execute('CREATE TRIGGER test_registration_failure BEFORE INSERT ON trader FOR EACH ROW EXECUTE FUNCTION test_registration_failure()')
    email=f'rollback-{uuid4().hex}@example.test'
    try:
        with pytest.raises(psycopg.Error):
            register_account(Database(Settings.from_env()), Registration(full_name='Fail Registration Fixture',email=email,password='synthetic-registration-password'))
        with db_connect() as conn:
            assert conn.execute('SELECT count(*) FROM user_account WHERE email=%s',(email,)).fetchone()[0]==0
    finally:
        with db_connect() as conn:
            conn.execute('DROP TRIGGER test_registration_failure ON trader')
            conn.execute('DROP FUNCTION test_registration_failure()')


@pytest.mark.parametrize('changes', [{'role':'COMPLIANCE_ADMIN'},{'cash_balance':100},{'verified':True},{'password':'é'*40},{'full_name':'\n'},{'email':'bad'}])
def test_rejects_privilege_and_invalid_fields(changes):
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Registration(**({'full_name':'Valid Name','email':'valid@example.test','password':'synthetic-registration-password'}|changes))


def test_provisioned_users_are_isolated_and_repeated_provision_is_safe(registrations):
    from backend.services.trader_provisioning import provision_trader_identity, registration_ready
    from scripts.setup_database_identity import read_manifest, provision_test_traders
    settings=Settings.from_env()
    receipts=[registrations(),registrations()]
    with db_connect() as conn:
        tids=[row[0] for row in conn.execute('SELECT trader_id FROM registration_state WHERE user_account_id=ANY(%s)',([r['registration_id'] for r in receipts],))]
        for tid in tids:conn.execute("UPDATE registration_state SET status='PENDING_PROVISIONING' WHERE trader_id=%s",(tid,))
    try:
        with ThreadPoolExecutor(2) as pool:
            results=list(pool.map(lambda tid:provision_trader_identity(tid,settings,expected_database=settings.postgres_db),tids))
        assert all(r['status']=='ACTIVE' for r in results)
        before=read_manifest(settings.trader_credentials_file)['traders']
        for tid in tids:
            assert registration_ready(tid,settings)
            provision_trader_identity(tid,settings,expected_database=settings.postgres_db)
            assert Database(settings).trader_query(tid,'SELECT * FROM margin_account WHERE trader_id=%s',(next(x for x in tids if x!=tid),))==[]
        after=read_manifest(settings.trader_credentials_file)['traders']
        assert {str(t):before[str(t)] for t in tids}=={str(t):after[str(t)] for t in tids}
    finally:
        provision_test_traders(tids,remove=True)


def test_public_auth_role_has_no_role_creation_or_financial_write_privileges():
    from psycopg.errors import InsufficientPrivilege
    settings=Settings.from_env();database=Database(settings)
    with database._connect_as(settings.postgres_auth_user,settings.postgres_auth_password) as conn:
        row=conn.execute('SELECT rolcreaterole,rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
        assert not any(row.values())
        with pytest.raises(InsufficientPrivilege):conn.execute('DELETE FROM margin_account WHERE false')


def test_provisioning_recovers_after_role_commit_without_rotating_credentials(registrations,monkeypatch):
    from backend.services import trader_provisioning as provisioning
    from scripts.setup_database_identity import read_manifest,provision_test_traders
    settings=Settings.from_env()
    receipt=registrations()
    with db_connect() as conn:
        tid=conn.execute("UPDATE registration_state SET status='PENDING_PROVISIONING' WHERE user_account_id=%s RETURNING trader_id",(receipt['registration_id'],)).fetchone()[0]
    verify=provisioning.verify_trader_identity
    def unavailable(*args):raise RuntimeError('Injected verification outage after role COMMIT')
    try:
        monkeypatch.setattr(provisioning,'verify_trader_identity',unavailable)
        with pytest.raises(RuntimeError,match='Injected verification outage'):
            provisioning.provision_trader_identity(tid,settings,expected_database=settings.postgres_db)
        before=read_manifest(settings.trader_credentials_file)['traders'][str(tid)]
        with db_connect() as conn:
            assert conn.execute('SELECT status FROM registration_state WHERE trader_id=%s',(tid,)).fetchone()[0]=='FAILED_RETRYABLE'
        monkeypatch.setattr(provisioning,'verify_trader_identity',verify)
        assert provisioning.provision_trader_identity(tid,settings,expected_database=settings.postgres_db)['status']=='ACTIVE'
        assert read_manifest(settings.trader_credentials_file)['traders'][str(tid)]==before
        assert provisioning.registration_ready(tid,settings)
    finally:
        provision_test_traders([tid],remove=True)
