"""Approved identity-boundary setup. Private manifest; no password resets or data seeds."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
from uuid import UUID
from psycopg import sql
from backend.config import ROOT
from backend.stores.trader_identity import trader_role,verify_password_authentication
from scripts.verify_schema import db_connect


@contextmanager
def manifest_lock(path):
    lock=Path(str(path)+'.lock')
    descriptor=os.open(lock,os.O_CREAT|os.O_RDWR,0o600)
    with os.fdopen(descriptor,'r+') as stream:
        fcntl.flock(stream,fcntl.LOCK_EX)
        yield


def read_manifest(path):
    path=Path(path)
    if not path.exists():return {'services':{},'traders':{}}
    if path.stat().st_uid!=os.getuid() or path.stat().st_mode & 0o077:raise ValueError('Credential manifest must be private')
    return json.loads(path.read_text())


def write_manifest(path,value):
    path=Path(path)
    descriptor,temporary=tempfile.mkstemp(prefix=path.name+'.',dir=path.parent)
    try:
        with os.fdopen(descriptor,'w') as stream:
            os.fchmod(stream.fileno(),0o600)
            json.dump(value,stream)
            stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if os.path.exists(temporary):os.unlink(temporary)


def login_role(conn,name,password,known=False):
    row=conn.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls,rolinherit,rolcanlogin FROM pg_roles WHERE rolname=%s',(name,)).fetchone()
    if row:
        if not known or any(row[:5]) or not row[5]:
            raise ValueError('Existing role needs verified private credentials; refusing changes')
        return
    conn.execute(sql.SQL('CREATE ROLE {} LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {}').format(sql.Identifier(name),sql.Literal(password)))


def add_traders(conn,manifest,traders):
    database=conn.info.dbname
    for trader in traders:
        tid=str(UUID(str(trader)))
        entry=manifest['traders'].get(tid)
        password=entry['password'] if entry else secrets.token_urlsafe(36)
        role=trader_role(tid)
        if entry and entry['user']!=role:raise ValueError('Trader credential role mismatch')
        login_role(conn,role,password,known=entry is not None)
        conn.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(database),sql.Identifier(role)))
        conn.execute(sql.SQL('GRANT trader_role TO {}').format(sql.Identifier(role)))
        manifest['traders'][tid]={'user':role,'password':password}


def provision_test_traders(traders,*,remove=False):
    """Scoped native fixtures only; no-op for legacy deployments. Never runtime API."""
    if os.environ.get('DATABASE_IDENTITY_MODE')!='isolated':return
    path=Path(os.environ['TRADER_DATABASE_CREDENTIALS_FILE'])
    with manifest_lock(path):
        manifest=read_manifest(path)
        with db_connect() as conn:
            if remove:
                for trader in traders:
                    tid=str(UUID(str(trader)));entry=manifest['traders'].pop(tid,None)
                    if not entry:continue
                    role=trader_role(tid)
                    conn.execute(sql.SQL('REVOKE CONNECT ON DATABASE {} FROM {}').format(sql.Identifier(conn.info.dbname),sql.Identifier(role)))
                    conn.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)))
            else:add_traders(conn,manifest,traders)
        write_manifest(path,manifest)
        if not remove:
            for trader in traders:
                verify_password_authentication(manifest['connection']['host'],manifest['connection']['port'],
                    manifest['database'],trader_role(trader))


def environment(manifest_path):
    data=read_manifest(manifest_path)
    if not data.get('authentication_verified'):raise ValueError('Database password authentication has not been verified')
    financial,auth,admin=(data['services'][name] for name in ('financial','auth','compliance'))
    return {'POSTGRES_DB':data['database'],'POSTGRES_HOST':data['connection']['host'],'POSTGRES_ADMIN_HOST':data['connection']['host'],
        'POSTGRES_PORT':str(data['connection']['port']),'POSTGRES_ADMIN_USER':data['connection']['admin_user'],'DATABASE_IDENTITY_MODE':'isolated','POSTGRES_RUNTIME_USER':financial['user'],
        'POSTGRES_RUNTIME_PASSWORD':financial['password'],'POSTGRES_AUTH_USER':auth['user'],
        'POSTGRES_AUTH_PASSWORD':auth['password'],'POSTGRES_COMPLIANCE_USER':admin['user'],
        'POSTGRES_COMPLIANCE_PASSWORD':admin['password'],'TRADER_DATABASE_CREDENTIALS_FILE':str(manifest_path)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',required=True);parser.add_argument('--manifest',type=Path,required=True)
    parser.add_argument('--financial-role',default='tradegraph_financial');parser.add_argument('--auth-role',default='tradegraph_auth')
    parser.add_argument('--compliance-role',default='tradegraph_compliance');parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    roles={'financial':args.financial_role,'auth':args.auth_role,'compliance':args.compliance_role}
    if len(set(roles.values()))!=3 or any(not re.fullmatch('[a-z][a-z0-9_]{0,62}',name) for name in roles.values()):raise ValueError('Distinct valid service role names required')
    if not args.apply:
        print('Dry run: separate three service roles, per-trader logins and five RLS boundaries; no changes');return
    with manifest_lock(args.manifest):
        manifest=read_manifest(args.manifest)
        if manifest.get('database',args.database)!=args.database:raise ValueError('Manifest database differs')
        manifest['database']=args.database
        with db_connect() as conn:
            if conn.info.dbname!=args.database:raise ValueError('Explicit database differs from admin connection')
            for kind,name in roles.items():
                entry=manifest['services'].get(kind)
                if entry and entry['user']!=name:raise ValueError('Existing service identity differs')
                password=entry['password'] if entry else secrets.token_urlsafe(36)
                login_role(conn,name,password,known=entry is not None)
                conn.execute(sql.SQL('GRANT CONNECT ON DATABASE {} TO {}').format(sql.Identifier(args.database),sql.Identifier(name)))
                manifest['services'][kind]={'user':name,'password':password}
            template=(ROOT/'db/migrations/20261116_trader_read_isolation.sql').read_text()
            conn.execute(sql.SQL(template).format(financial_role=sql.Identifier(args.financial_role),
                auth_role=sql.Identifier(args.auth_role),compliance_role=sql.Identifier(args.compliance_role)),prepare=False)
            add_traders(conn,manifest,[r[0] for r in conn.execute('SELECT id FROM public.trader')])
            manifest['connection']={'host':conn.info.host,'port':conn.info.port,'admin_user':conn.info.user}
        manifest['authentication_verified']=False
        write_manifest(args.manifest,manifest)
        for entry in list(manifest['services'].values())+list(manifest['traders'].values()):
            verify_password_authentication(manifest['connection']['host'],manifest['connection']['port'],args.database,entry['user'])
        manifest['authentication_verified']=True
        write_manifest(args.manifest,manifest)
    print('Applied separate identities/RLS to the explicitly selected database; private credentials written')


if __name__=='__main__':
    try:main()
    except Exception as exc:raise SystemExit('Identity setup failed: '+type(exc).__name__+'; no credentials logged') from None
