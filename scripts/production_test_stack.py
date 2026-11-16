"""Owned subprocesses for isolated real Caddy HTTPS/WSS tests. No public deployment."""
import os
from pathlib import Path
import signal
import ssl
import subprocess
import sys
import tempfile
import time

import httpx
from backend.config import ROOT, Settings
from scripts.run_local import check_port_available
from scripts.reconcile_restart import diagnose
from backend.stores.postgres import Database


class ProductionTestStack:
    def __init__(self, caddy, root=None, *, backend_port=58000, next_port=53001,
                 https_port=58443, http_port=58080):
        self.settings = Settings.from_env()
        if not self.settings.postgres_db.startswith('tradegraph_test_'):
            raise ValueError('Explicit isolated test database required')
        self.caddy = str(Path(caddy).resolve())
        self.root = Path(tempfile.mkdtemp(prefix='tls-', dir=root))
        self.root.chmod(0o700)
        self.origin = f'https://localhost:{https_port}'
        self.http_origin = f'http://localhost:{http_port}'
        self.backend = f'http://127.0.0.1:{backend_port}'
        self.frontend = f'http://127.0.0.1:{next_port}'
        self.ports = (backend_port, next_port, https_port, http_port)
        self.processes = {}
        self.streams = []
        self.env = dict(os.environ, APP_ORIGIN=self.origin, ALLOW_INSECURE_LOOPBACK_ORIGIN='false',
                        TRADEGRAPH_DOMAIN=f'localhost:{https_port}', NODE_ENV='production',
                        TRADEGRAPH_MODE='live', FASTAPI_BASE_URL=self.backend,
                        NEXT_INTERNAL_ORIGIN=self.frontend, XDG_DATA_HOME=str(self.root/'data'),
                        XDG_CONFIG_HOME=str(self.root/'config'), TRADEGRAPH_TEST_ROOT=str(self.root))
        for name in list(self.env):
            if name.startswith('POSTGRES_ADMIN') or name in ('PGPASSWORD','PGPASSFILE','POSTGRES_PASSWORD','POSTGRES_USER'):
                del self.env[name]
        self.commands = {
            'backend': ([sys.executable,'-m','uvicorn','scripts.production_test_app:create_app','--factory','--host','127.0.0.1',
                         '--port',str(backend_port),'--workers','1','--ws-max-size','2048','--no-access-log'], ROOT),
            'frontend': (['node','node_modules/next/dist/bin/next','start','--hostname','127.0.0.1','--port',str(next_port)], ROOT/'frontend'),
            'proxy': ([self.caddy,'run','--config',str(self.root/'Caddyfile'),'--adapter','caddyfile'], ROOT),
        }

    def prepare(self):
        for port in self.ports:
            check_port_available('127.0.0.1',port)
        if not (ROOT/'frontend/.next/BUILD_ID').is_file():
            raise ValueError('Build the production frontend before TLS tests')
        cert, key = self.root/'cert.pem', self.root/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','2',
                        '-keyout',str(key),'-out',str(cert),'-subj','/CN=localhost',
                        '-addext','subjectAltName=DNS:localhost,IP:127.0.0.1'],
                       check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        key.chmod(0o600)
        self.ssl = ssl.create_default_context(cafile=str(cert))
        source = (ROOT/'deploy/Caddyfile.example').read_text()
        # Validate the unchanged production configuration with the real validator.
        subprocess.run([self.caddy,'validate','--config',str(ROOT/'deploy/Caddyfile.example'),'--adapter','caddyfile'],
                       env=self.env,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        # Only test endpoints and an explicitly trusted local certificate differ.
        source=source.replace('{\n    admin off',f'{{\n    http_port {self.ports[3]}\n    default_bind 127.0.0.1\n    admin off',1)
        source=source.replace('{$TRADEGRAPH_DOMAIN:tradegraph.example} {',
                              '{$TRADEGRAPH_DOMAIN:tradegraph.example} {\n    tls '+str(cert)+' '+str(key),1)
        source=source.replace('127.0.0.1:8000',f'127.0.0.1:{self.ports[0]}').replace('127.0.0.1:3001',f'127.0.0.1:{self.ports[1]}')
        (self.root/'Caddyfile').write_text(source)
        subprocess.run([self.caddy,'validate','--config',str(self.root/'Caddyfile'),'--adapter','caddyfile'],
                       env=self.env,check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

    def spawn(self,name):
        command,cwd=self.commands[name]
        stream=(self.root/(name+'.log')).open('a');os.chmod(stream.name,0o600)
        self.streams.append(stream)
        self.processes[name]=subprocess.Popen(command,cwd=cwd,env=self.env,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)

    def wait(self,name,timeout=60):
        url={'backend':self.backend+'/health','frontend':self.frontend+'/api/session','proxy':self.origin+'/api/session'}[name]
        deadline=time.monotonic()+timeout
        with httpx.Client(verify=getattr(self,'ssl',True),trust_env=False,timeout=3) as client:
            while time.monotonic()<deadline:
                if self.processes[name].poll() is not None:
                    raise RuntimeError(name+' stopped; inspect private test log')
                try:
                    response=client.get(url)
                    if response.status_code==200 and (name!='backend' or response.json()['trading_ready']):
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(.1)
        raise RuntimeError(name+' startup timeout; inspect private test log')

    def stop(self,name):
        process=self.processes.get(name)
        if process is not None and process.poll() is None:
            os.killpg(process.pid,signal.SIGTERM)
            try:
                process.wait(timeout=40)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid,signal.SIGKILL);process.wait()

    def restart(self,name):
        if name=='backend':
            state=diagnose(Database(self.settings))
            if state['active_orders'] or state['volume_mismatches']:
                raise RuntimeError('Unsafe matching restart refused; preserve all orders')
        self.stop(name)
        if name=='backend' and not diagnose(Database(self.settings))['cold_start_safe']:
            raise RuntimeError('Unsafe financial state after stop; restart refused')
        self.spawn(name);self.wait(name)

    def __enter__(self):
        try:
            self.prepare()
            for name in ('backend','frontend','proxy'):
                self.spawn(name);self.wait(name)
            return self
        except BaseException:
            self.__exit__(None,None,None)
            raise

    def __exit__(self,*_):
        for name in ('proxy','frontend','backend'):
            self.stop(name)
        for stream in self.streams:
            stream.close()
