"""Checked local stack lifecycle. Automatically provisions trader signups; never seeds, resets or cancels orders."""
import argparse
import importlib.util
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import urlsplit
from dotenv import dotenv_values
import httpx
import redis
from neo4j import GraphDatabase
from backend.config import ROOT, Settings
from backend.stores.postgres import Database
from backend.stores.trader_identity import credentials, verify_password_authentication
from backend.api.websocket import trusted_origin
from scripts.reconcile_restart import diagnose


def environment(path):
    values={k:v for k,v in dotenv_values(path,interpolate=False).items() if v is not None}
    values.update(os.environ)
    return values


def check_port_available(host,port):
    # Match server restart semantics: TIME_WAIT connections are not live listeners.
    # listen() still rejects a conflicting server on platforms permitting reused bind.
    with socket.socket() as probe:
        probe.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        try:
            probe.bind((host,port))
            probe.listen(1)
        except OSError:
            raise ValueError('A requested local port is occupied; no process was started') from None


def preflight(values):
    if importlib.util.find_spec('websockets') is None:raise ValueError('Install requirements.txt before starting WebSocket transport')
    settings=Settings.from_env(values)
    origin=trusted_origin(settings)
    public=urlsplit(origin)
    frontend=values.get('NEXT_INTERNAL_ORIGIN','http://127.0.0.1:3001')
    backend=values.get('FASTAPI_BASE_URL','http://127.0.0.1:8000')
    targets=[urlsplit(value) for value in (origin,frontend,backend)]
    if any(t.scheme!='http' or t.hostname!='127.0.0.1' or not t.port or t.path not in ('','/') or t.query or t.fragment or t.username or t.password for t in targets):
        raise ValueError('Local workflow requires three explicit 127.0.0.1 HTTP origins')
    if len({t.port for t in targets})!=3:raise ValueError('Public, Next and FastAPI ports must differ')
    if not re.fullmatch('[a-fA-F0-9]{64}',values.get('SESSION_ENCRYPTION_KEY','')):
        raise ValueError('Private 64-hex session encryption key required')
    if settings.database_identity_mode!='isolated':raise ValueError('Isolated database identities required')
    database=Database(settings)
    for user in (settings.postgres_runtime_user,settings.postgres_auth_user,settings.postgres_compliance_user):
        verify_password_authentication(settings.postgres_host,settings.postgres_port,settings.postgres_db,user)
    for name in ('order_request_identity','registration_state','registration_policy'):
        # Auth intentionally has no policy-table read; existence is public catalog metadata.
        if database.auth_query('SELECT to_regclass(%s) AS object',('public.'+name,))[0]['object'] is None:
            raise ValueError('Required migration is missing')
    if database.auth_query("SELECT to_regprocedure('public.register_trader(text,text,text)') AS object")[0]['object'] is None:
        raise ValueError('Registration function is missing')
    database.auth_query('SELECT status FROM public.registration_state LIMIT 0')
    state=diagnose(database)
    if not state['cold_start_safe']:raise ValueError('Another owner or unresolved financial state requires operator reconciliation; nothing was changed')
    for row in database.auth_query("SELECT t.id FROM public.trader t LEFT JOIN public.registration_state r ON r.trader_id=t.id WHERE r.status IS NULL OR r.status='ACTIVE'"):
        credentials(settings.trader_credentials_file,row['id'])
    client=redis.Redis.from_url(settings.redis_url,socket_connect_timeout=2,socket_timeout=2)
    try:client.ping()
    finally:client.close()
    with GraphDatabase.driver(settings.neo4j_uri,auth=(settings.neo4j_user,settings.neo4j_password),connection_timeout=3) as graph:
        graph.verify_connectivity()
    for target in targets:
        check_port_available(target.hostname,target.port)
    return origin,frontend,backend


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file',type=Path,default=ROOT/'.env')
    parser.add_argument('--check',action='store_true')
    parser.add_argument('--provision-admin-password-file',type=Path,help='Private operator password file; used only by the separate signup worker')
    parser.add_argument('--log-dir',type=Path,default=Path('/tmp/tradegraph-local-logs'))
    args=parser.parse_args()
    values=environment(args.env_file)
    password_file=args.provision_admin_password_file or Path(values.get('REGISTRATION_ADMIN_PASSWORD_FILE',str(Path(values.get('TRADER_DATABASE_CREDENTIALS_FILE','')).parent/'admin-password')))
    operator_env=dict(values)
    if password_file.is_file():
        info=password_file.stat()
        if info.st_uid!=os.getuid() or info.st_mode & 0o077:
            raise ValueError('Registration operator password file must be owner-only')
        operator_env['PGPASSWORD']=password_file.read_text().strip()
    if not operator_env.get('PGPASSWORD'):
        raise ValueError('Automatic signup requires --provision-admin-password-file or operator PGPASSWORD; it is never passed to the API')
    origin,frontend,backend=preflight(values)
    if args.check:print('Preflight passed: services, migrations, private identities, ports and safe cold start');return
    if not (ROOT/'frontend/.next/BUILD_ID').is_file():raise ValueError('Run npm run build in frontend first')
    args.log_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
    env=dict(values,APP_ORIGIN=origin,FASTAPI_BASE_URL=backend,NEXT_INTERNAL_ORIGIN=frontend,NODE_ENV='production',TRADEGRAPH_MODE='live')
    for name in list(env):
        if name.startswith('POSTGRES_ADMIN') or name in ('PGPASSWORD','PGPASSFILE','POSTGRES_PASSWORD','POSTGRES_USER'):
            del env[name]
    processes=[];streams=[]
    def stop(signum=None,frame=None):raise KeyboardInterrupt()
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    def spawn(name,command,cwd=ROOT,*,child_env=None):
        stream=(args.log_dir/(name+'.log')).open('a');streams.append(stream)
        process=subprocess.Popen(command,cwd=cwd,env=child_env if child_env is not None else env,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        processes.append(process)
    def wait_for(url,ready,timeout=45):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if any(p.poll() is not None for p in processes):raise RuntimeError('A stack process stopped; inspect private local logs')
            try:
                response=httpx.get(url,timeout=3)
                if ready(response):return
            except httpx.HTTPError:pass
            time.sleep(.25)
        raise RuntimeError('Startup health check timed out; inspect local logs')
    try:
        spawn('registration-worker',[sys.executable,'-m','scripts.auto_provision_registrations'],child_env=operator_env)
        spawn('backend',[sys.executable,'-m','uvicorn','backend.api.main:app','--host','127.0.0.1','--port',str(urlsplit(backend).port),'--workers','1','--ws-max-size','2048','--no-access-log'])
        wait_for(backend+'/health',lambda response:response.status_code==200 and response.json().get('trading_ready') is True)
        spawn('frontend',['node','node_modules/next/dist/bin/next','start','--hostname','127.0.0.1','--port',str(urlsplit(frontend).port)],ROOT/'frontend')
        wait_for(frontend+'/api/session',lambda response:response.status_code==200)
        spawn('proxy',['node',str(ROOT/'deploy/local-proxy.mjs')])
        wait_for(origin+'/api/session',lambda response:response.status_code==200)
        print('Stack ready. Canonical browser URL: '+origin,flush=True)
        while all(p.poll() is None for p in processes):time.sleep(.5)
        raise RuntimeError('Stack process exited unexpectedly')
    except KeyboardInterrupt:pass
    finally:
        for process in reversed(processes):
            if process.poll() is None:os.killpg(process.pid,signal.SIGTERM)
        for process in reversed(processes):
            try:process.wait(timeout=40)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);process.wait()
        for stream in streams:stream.close()


if __name__=='__main__':
    try:main()
    except Exception as error:raise SystemExit('Startup stopped: '+type(error).__name__+'; inspect configuration/services without printing secrets') from None
