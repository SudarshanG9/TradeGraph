"""Trusted local signup worker; database owner credentials never enter the API."""
import argparse
import os
import signal
from threading import Event
from psycopg import sql
from backend.config import ROOT, Settings
from backend.services.trader_provisioning import provision_trader_identity
from scripts.verify_schema import db_connect


def disable_approval(settings):
    with db_connect() as conn:
        if conn.info.dbname != settings.postgres_db:
            raise ValueError('Registration worker database mismatch')
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('tradegraph-registration-migration'))")
        conn.execute(sql.SQL((ROOT/'db/migrations/20261117_registration_no_approval.sql').read_text()).format(
            auth_role=sql.Identifier(settings.postgres_auth_user)),prepare=False)


def provision_batch(settings):
    with db_connect() as conn:
        if conn.info.dbname != settings.postgres_db:
            raise ValueError('Registration worker database mismatch')
        rows=conn.execute("SELECT trader_id FROM registration_state WHERE status IN ('PENDING_PROVISIONING','FAILED_RETRYABLE') ORDER BY updated_at LIMIT 10").fetchall()
    for (tid,) in rows:
        try:provision_trader_identity(tid,settings,expected_database=settings.postgres_db)
        except Exception:pass  # The existing workflow retains FAILED_RETRYABLE.
    return len(rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once',action='store_true')
    parser.add_argument("--parent-pid",type=int,help="Stop when the owning local runner exits")
    args=parser.parse_args()
    settings=Settings.from_env()
    disable_approval(settings)
    stopped=Event()
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,lambda *_:stopped.set())
    while not stopped.is_set():
        if args.parent_pid:
            try:os.kill(args.parent_pid,0)
            except ProcessLookupError:break
        try:provision_batch(settings)
        except Exception:print('Automatic account setup temporarily unavailable; retrying',flush=True)
        if args.once:break
        stopped.wait(2)


if __name__=='__main__':main()
