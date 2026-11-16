#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
"${PYTHON:-.venv/bin/python}" - "$@" <<'PY'
import argparse
import os
import secrets
import subprocess
from getpass import getuser
from pathlib import Path
from psycopg import sql as pgsql
from dotenv import dotenv_values
from scripts.verify_schema import db_connect, EXPECTED_TABLES

parser = argparse.ArgumentParser(description='Incremental native backend installation; no bootstrap or seeds')
parser.add_argument('--phase', type=int, default=2, choices=[2, 3, 4, 5])
args = parser.parse_args()
values = {k:v for k,v in dotenv_values('.env').items() if v is not None} | dict(os.environ)
prefixes=('replace_','change_me','your_')
runtime_secret_invalid=not values.get('POSTGRES_RUNTIME_PASSWORD','').strip() or values.get('POSTGRES_RUNTIME_PASSWORD','').lower().startswith(prefixes)
if args.phase>=3 and (not Path('.env').is_file() or subprocess.run(['git','check-ignore','-q','.env']).returncode):
    raise SystemExit('Create an ignored .env from .env.example before runtime installation')
with db_connect() as conn:
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('tradegraph-backend-install'))")
    tables = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
    if not EXPECTED_TABLES <= tables or tables - EXPECTED_TABLES - {'order_request_identity'}:
        raise SystemExit('Expected the initialized 13-table schema; refusing installation')
    signature = 'public.place_and_reserve_order(uuid,integer,text,bigint,bigint)'
    if conn.execute('SELECT to_regprocedure(%s)', (signature,)).fetchone()[0] is None:
        sql = Path('db/procedures/place_and_reserve_order.sql').read_text().strip()
        sql = sql.removeprefix('BEGIN;').removesuffix('COMMIT;')
        conn.execute(sql, prepare=False)
        print('Installed existing reservation function')
    else:
        print('Reservation already installed; preserved existing function')
    if args.phase >= 3:
        user = values.get('POSTGRES_RUNTIME_USER', 'tradegraph_runtime').strip()
        if not user or user in ('postgres','trader_role','compliance_admin_role',getuser(),values.get('POSTGRES_USER'),values.get('POSTGRES_ADMIN_USER')):
            raise SystemExit('Refusing owner/admin runtime identity')
        role = conn.execute('SELECT rolsuper,rolcreaterole,rolcreatedb,rolbypassrls,rolinherit,rolcanlogin FROM pg_roles WHERE rolname=%s', (user,)).fetchone()
        if role and (any(role[:5]) or not role[5]):
            raise SystemExit('Existing runtime identity must be nonprivileged NOINHERIT LOGIN; refusing to modify it')
        if role is not None and runtime_secret_invalid:
            raise SystemExit('Existing runtime role requires its current password in .env; no credential reset performed')
        if runtime_secret_invalid:
            values['POSTGRES_RUNTIME_PASSWORD']=secrets.token_urlsafe(36)
            with Path('.env').open('a') as stream:
                stream.write('\nPOSTGRES_RUNTIME_PASSWORD='+values['POSTGRES_RUNTIME_PASSWORD']+'\n')
            print('Generated missing/placeholder secret for a NEW runtime login in ignored .env')
        if len(values.get('JWT_SECRET','').strip())<32 or values.get('JWT_SECRET','').lower().startswith(prefixes):
            with Path('.env').open('a') as stream:
                stream.write('\nJWT_SECRET='+secrets.token_urlsafe(48)+'\n')
            print('Generated missing/invalid signing key for the new API in ignored .env')
        if role is None:
            conn.execute(pgsql.SQL('CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {}').format(pgsql.Identifier(user), pgsql.Literal(values['POSTGRES_RUNTIME_PASSWORD'])))
        conn.execute(pgsql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(pgsql.Identifier(values.get('POSTGRES_DB','tradegraph')), pgsql.Identifier(user)))
        conn.execute(pgsql.SQL('GRANT USAGE ON SCHEMA public TO {}').format(pgsql.Identifier(user)))
        conn.execute(pgsql.SQL('GRANT trader_role, compliance_admin_role TO {}').format(pgsql.Identifier(user)))
        conn.execute(pgsql.SQL('GRANT SELECT ON user_account,trader,instrument,fee_tier,margin_account,"order",order_history,execution,position,desk TO {}').format(pgsql.Identifier(user)))
        conn.execute(pgsql.SQL('GRANT USAGE ON SEQUENCE execution_id_seq TO {}').format(pgsql.Identifier(user)))
        conn.execute(pgsql.SQL('GRANT EXECUTE ON FUNCTION public.place_and_reserve_order(uuid,integer,text,bigint,bigint) TO {}').format(pgsql.Identifier(user)))
        print('Runtime identity/grants verified and installed; no user-facing role added')
    if args.phase >= 4:
        for name in ('db/triggers/update_positions.sql','db/procedures/settle_execution.sql','db/procedures/cancel_order.sql'):
            conn.execute(Path(name).read_text(), prepare=False)
        for signature in ('public.settle_execution(bigint,integer,bigint,bigint,uuid,uuid,bigint,bigint,bigint,timestamptz)', 'public.cancel_order(bigint,uuid)'):
            conn.execute(pgsql.SQL('GRANT EXECUTE ON FUNCTION {} TO {}').format(pgsql.SQL(signature),pgsql.Identifier(user)))
        print('Installed atomic settlement, cancellation, position trigger and immutable-basis guards')
    if args.phase >= 5:
        for name in ('db/views/order_book_view.sql','db/queries/query_indexes.sql'):
            conn.execute(Path(name).read_text(), prepare=False)
        print('Installed persisted book view and compatible BRIN/covering indexes')
print(f'Incremental Phase {args.phase} installation committed; existing rows preserved')
PY
