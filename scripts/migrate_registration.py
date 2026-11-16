"""Apply additive registration migration to an explicitly selected database."""
import argparse
from pathlib import Path
from psycopg import sql
from scripts.verify_schema import db_connect


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', required=True)
    parser.add_argument('--auth-role', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--synthetic-demo', action='store_true', help='Explicitly bypass email verification for synthetic accounts only')
    parser.add_argument('--starter-cash', type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.starter_cash <= 2**63-1 or (args.starter_cash and not args.synthetic_demo):
        parser.error('Starter cash requires explicit synthetic demo policy')
    if not args.apply:
        print('Dry run: normalized email preflight, additive registration records and restricted function')
        return
    with db_connect() as conn:
        if conn.info.dbname != args.database:
            raise ValueError('Explicit database differs from admin connection')
        if not conn.execute('SELECT 1 FROM pg_roles WHERE rolname=%s AND NOT rolsuper AND NOT rolcreaterole AND NOT rolbypassrls', (args.auth_role,)).fetchone():
            raise ValueError('Dedicated restricted authentication role required')
        conn.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ('tradegraph-registration-migration',))
        conn.execute(sql.SQL(Path('db/migrations/20261116_user_registration.sql').read_text()).format(auth_role=sql.Identifier(args.auth_role)), prepare=False)
        conn.execute('UPDATE public.registration_policy SET synthetic_demo=%s,initial_cash=%s WHERE singleton', (args.synthetic_demo,args.starter_cash))
    print('Applied registration migration and explicit funding/verification policy; no existing account changed')


if __name__ == '__main__':
    main()
