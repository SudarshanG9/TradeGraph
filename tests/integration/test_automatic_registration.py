"""No human approval; activation still verifies real trader credentials and RLS."""
from fastapi.testclient import TestClient
from backend.api.main import create_app
from backend.config import Settings
from backend.services.trader_provisioning import registration_ready
from scripts.auto_provision_registrations import disable_approval, provision_batch
from scripts.setup_database_identity import provision_test_traders
from scripts.verify_schema import db_connect
from tests.integration.test_registration import registrations


def test_existing_and_new_traders_activate_without_approval(registrations):
    settings=Settings.from_env()
    old=registrations()
    disabled=registrations()
    with db_connect() as conn:
        original=conn.execute('SELECT synthetic_demo,initial_cash FROM registration_policy').fetchone()
        conn.execute('UPDATE registration_policy SET synthetic_demo=false,initial_cash=0')
        conn.execute("UPDATE registration_state SET status='PENDING_VERIFICATION' WHERE user_account_id=%s",(old['registration_id'],))
        conn.execute("UPDATE registration_state SET status='DISABLED' WHERE user_account_id=%s",(disabled['registration_id'],))
    tids=[]
    try:
        disable_approval(settings)
        new=registrations()
        assert new['status']=='PENDING_PROVISIONING'
        with db_connect() as conn:
            tids=[r[0] for r in conn.execute('SELECT trader_id FROM registration_state WHERE user_account_id=ANY(%s)',([old['registration_id'],new['registration_id']],))]
            assert conn.execute('SELECT cash_balance FROM margin_account WHERE trader_id=(SELECT trader_id FROM registration_state WHERE user_account_id=%s)',(new['registration_id'],)).fetchone()[0]==0
        provision_batch(settings)
        assert all(registration_ready(tid,settings) for tid in tids)
        with db_connect() as conn:
            assert conn.execute('SELECT status FROM registration_state WHERE user_account_id=%s',(disabled['registration_id'],)).fetchone()[0]=='DISABLED'
            email=conn.execute('SELECT email FROM user_account WHERE id=%s',(new['registration_id'],)).fetchone()[0]
        with TestClient(create_app(settlement=False)) as client:
            assert client.post('/login',json={'email':email,'password':'synthetic-registration-password'}).status_code==200
    finally:
        provision_test_traders(tids,remove=True)
        with db_connect() as conn:
            conn.execute('UPDATE registration_policy SET synthetic_demo=%s,initial_cash=%s',original)
