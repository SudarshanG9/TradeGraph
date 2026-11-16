"""Operator-only recoverable provisioning. Never imported by the public router."""
from dataclasses import replace
from pathlib import Path
from uuid import UUID
import secrets
from backend.stores.trader_identity import trader_role, verify_password_authentication
from backend.stores.postgres import Database
from scripts.setup_database_identity import manifest_lock, read_manifest, write_manifest, add_traders
from scripts.verify_schema import db_connect


def verify_trader_identity(trader_id, settings):
    database = Database(settings)
    verify_password_authentication(settings.postgres_host, settings.postgres_port, settings.postgres_db, trader_role(trader_id))
    with database.trader_context(trader_id) as conn:
        rows=conn.execute('SELECT trader_id FROM public.margin_account').fetchall()
        if len(rows)!=1 or str(rows[0]['trader_id'])!=str(trader_id):
            raise RuntimeError('Trader account/RLS verification failed')
        for table in ('order','order_history','position','order_request_identity'):
            if conn.execute(f'SELECT 1 FROM public."{table}" WHERE trader_id<>%s LIMIT 1',(trader_id,)).fetchone():
                raise RuntimeError('Cross-user visibility detected')
    return True


def registration_ready(trader_id, settings):
    rows=Database(settings).auth_query('SELECT status FROM public.registration_state WHERE trader_id=%s',(trader_id,))
    return bool(rows and rows[0]['status']=='ACTIVE' and verify_trader_identity(trader_id,settings))


def provision_trader_identity(trader_id, settings, *, expected_database):
    tid=str(UUID(str(trader_id)))
    path=Path(settings.trader_credentials_file)
    # All callers of this workflow serialize the private file and PostgreSQL role.
    # Credentials are staged durably BEFORE role creation, making crash retry safe.
    with manifest_lock(path), db_connect() as owner:
        if owner.info.dbname!=expected_database or owner.info.dbname!=settings.postgres_db:
            raise ValueError('Explicit provisioning database mismatch')
        owner.execute('SELECT pg_advisory_lock(hashtext(%s))',('tradegraph-trader-provisioning',))
        row=owner.execute('SELECT status FROM public.registration_state WHERE trader_id=%s FOR UPDATE',(tid,)).fetchone()
        if not row or row[0] not in ('PENDING_PROVISIONING','FAILED_RETRYABLE','ACTIVE'):
            raise ValueError('Registration is not eligible for identity provisioning')
        manifest=read_manifest(path)
        if manifest.get('database')!=expected_database or not manifest.get('authentication_verified'):
            raise ValueError('Verified deployment manifest required')
        manifest['traders'].setdefault(tid,{'user':trader_role(tid),'password':secrets.token_urlsafe(36)})
        write_manifest(path,manifest)
        try:
            add_traders(owner,manifest,[tid])
            owner.commit()  # role must exist before independent credential verification
            verify_trader_identity(tid,replace(settings,trader_credentials_file=str(path)))
            owner.execute("UPDATE public.registration_state SET status='ACTIVE',updated_at=now() WHERE trader_id=%s",(tid,))
            owner.commit()
        except Exception:
            owner.rollback()
            owner.execute("UPDATE public.registration_state SET status='FAILED_RETRYABLE',updated_at=now() WHERE trader_id=%s AND status<>'DISABLED'",(tid,))
            owner.commit()
            raise
    return {'trader_id':tid,'status':'ACTIVE'}
