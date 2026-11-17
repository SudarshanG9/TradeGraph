"""Explicit new SCRAM/Redis test environment; refuses any existing target directory."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import subprocess
import sys
import psycopg
from psycopg import sql
from dotenv import dotenv_values
from backend.config import ROOT


def private_env(path,values):
    descriptor=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(descriptor,'w') as stream:
        for key,value in values.items():stream.write(key+'='+json.dumps(str(value))+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--database',default='tradegraph_test_registration')
    parser.add_argument('--pg-port',type=int,default=55434)
    parser.add_argument('--redis-port',type=int,default=6392)
    parser.add_argument('--source-env',type=Path,default=ROOT/'.env',help='Existing Neo4j connection configuration only is reused')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if args.root.exists() or not re.fullmatch(r'tradegraph_test_[a-z0-9_]+',args.database):
        raise ValueError('A new directory and tradegraph_test_ database name are required')
    for port in (args.pg_port,args.redis_port):
        if not 1024<=port<=65535:raise ValueError('Invalid test service port')
        with socket.socket() as probe:probe.bind(('127.0.0.1',port))
    if args.pg_port==args.redis_port:raise ValueError('Service ports must differ')
    commands={name:shutil.which(name) for name in ('initdb','pg_ctl','psql','redis-server')}
    if not all(commands.values()):raise ValueError('Native PostgreSQL (with pgvector) and Redis tools are required on PATH')
    source=dict(NEO4J_URI='bolt://127.0.0.1:7687',NEO4J_USER='neo4j')
    source.update({k:v for k,v in dotenv_values(args.source_env,interpolate=False).items() if v is not None})
    source.update({k:v for k,v in os.environ.items() if k.startswith('NEO4J_')})
    if any(not source.get(key) for key in ('NEO4J_URI','NEO4J_USER','NEO4J_PASSWORD')):
        raise ValueError('Configured Neo4j credentials required; tests scope fixtures by new trader IDs')
    if not args.apply:
        print('Dry run: create NEW UTF8/SCRAM cluster and dedicated Redis; apply schema/migrations, synthetic fixtures and private identities. Existing databases are untouched.');return
    root=args.root.resolve();root.mkdir(mode=0o700,parents=True)
    password=secrets.token_urlsafe(48);password_file=root/'admin-password'
    descriptor=os.open(password_file,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
    with os.fdopen(descriptor,'w') as stream:stream.write(password)
    log=(root/'setup.log').open('a')
    def run(command,env=None):subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,check=True)
    run([commands['initdb'],'-D',str(root/'data'),'--auth-local=scram-sha-256','--auth-host=scram-sha-256','--pwfile',str(password_file),'--encoding=UTF8','--no-locale'])
    with (root/'data/postgresql.conf').open('a') as stream:
        stream.write(f"\nlisten_addresses='127.0.0.1'\nport={args.pg_port}\nunix_socket_directories='{str(root).replace(chr(39),chr(39)*2)}'\npassword_encryption='scram-sha-256'\n")
    run([commands['pg_ctl'],'-D',str(root/'data'),'-l',str(root/'postgres.log'),'start','-w'])
    env=dict(os.environ,POSTGRES_DB=args.database,POSTGRES_HOST='127.0.0.1',POSTGRES_ADMIN_HOST='127.0.0.1',POSTGRES_PORT=str(args.pg_port),POSTGRES_ADMIN_USER=getpass.getuser(),PGPASSWORD=password)
    with psycopg.connect(host='127.0.0.1',port=args.pg_port,dbname='postgres',user=getpass.getuser(),password=password,autocommit=True) as connection:
        connection.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(args.database)))
        connection.execute(sql.SQL('CREATE ROLE tradegraph_runtime LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS PASSWORD {}').format(sql.Literal(secrets.token_urlsafe(36))))
    files=['db/schema.sql','db/seed.sql','db/seed_users.sql','db/procedures/place_and_reserve_order.sql','db/triggers/update_positions.sql','db/procedures/settle_execution.sql','db/procedures/cancel_order.sql','db/views/order_book_view.sql','db/queries/query_indexes.sql','db/migrations/20261116_request_identity.sql','db/migrations/20261116_bounded_archive.sql']
    for file in files:
        run([commands['psql'],'-X','-h','127.0.0.1','-p',str(args.pg_port),'-U',getpass.getuser(),'-d',args.database,'-v','ON_ERROR_STOP=1','-f',file],env)
    run([sys.executable,'-m','scripts.seed_live_bots','--apply'],env)
    run([sys.executable,'-m','scripts.setup_database_identity','--database',args.database,'--manifest',str(root/'identities.json'),'--apply'],env)
    from scripts.setup_database_identity import environment
    runtime_role=environment(root/'identities.json')['POSTGRES_RUNTIME_USER']
    run([sys.executable,'-m','scripts.migrate_recovery','--database',args.database,'--runtime-role',runtime_role,'--apply'],env)
    run([sys.executable,'-m','scripts.migrate_registration','--database',args.database,'--auth-role','tradegraph_auth','--apply','--synthetic-demo','--starter-cash','20000'],env)
    run([commands['redis-server'],'--bind','127.0.0.1','--port',str(args.redis_port),'--dir',str(root),'--appendonly','yes','--daemonize','yes','--pidfile',str(root/'redis.pid'),'--logfile',str(root/'redis.log')])
    from scripts.setup_database_identity import environment
    values={key:source[key] for key in ('NEO4J_URI','NEO4J_USER','NEO4J_PASSWORD')}
    values.update(environment(root/'identities.json'))
    values.update(REDIS_URL=f'redis://127.0.0.1:{args.redis_port}/0',APP_ORIGIN='http://127.0.0.1:3000',ALLOW_INSECURE_LOOPBACK_ORIGIN='true',FASTAPI_BASE_URL='http://127.0.0.1:8000',NEXT_INTERNAL_ORIGIN='http://127.0.0.1:3001',JWT_SECRET=secrets.token_urlsafe(48),SESSION_ENCRYPTION_KEY=secrets.token_hex(32))
    private_env(root/'runtime.env',values)
    run([sys.executable,"-m","scripts.auto_provision_registrations","--once"],dict(env,**values))
    log.close()
    print('Created isolated test environment. Private runtime configuration: '+str(root/'runtime.env'))
    print('Stop this cluster explicitly with pg_ctl -D '+str(root/'data')+' stop -m fast; stop only its Redis PID. Files are retained; no automatic data deletion.')


if __name__=='__main__':
    try:main()
    except Exception as error:raise SystemExit('Test setup stopped: '+type(error).__name__+'; inspect private setup log; no existing database reset') from None
