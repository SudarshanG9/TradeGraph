"""Explicit additive recovery migration. Never reads or prints a runtime password."""
import argparse
from pathlib import Path
from psycopg import sql
from scripts.verify_schema import db_connect
from backend.config import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--runtime-role', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        print('Dry run: atomic execution trigger, consumer progress, historical intent backfill and runtime-only grants')
        return
    with db_connect() as conn:
        if conn.info.dbname != args.database:
            raise ValueError('Explicit database does not match admin connection')
        conn.execute("SELECT pg_advisory_xact_lock(hashtext('tradegraph-recovery-install'))")
        for name in ('20261117_durable_event_outbox.sql','20261117_regime_replay_ordering.sql'):
            conn.execute((ROOT/'db/migrations'/name).read_text(), prepare=False)
        role = sql.Identifier(args.runtime_role)
        conn.execute(sql.SQL('GRANT SELECT ON public.event_outbox TO {}').format(role))
        conn.execute(sql.SQL('GRANT UPDATE(payload,completed_at,attempts,next_attempt_at,last_error) ON public.event_outbox TO {}').format(role))
    print('Recovery migration committed; core financial routines unchanged')


if __name__ == '__main__':
    main()
