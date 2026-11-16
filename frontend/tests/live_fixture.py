"""Operator fixture bridge for real browser acceptance in an explicit test DB."""
import json
import sys
import subprocess
from pathlib import Path
from urllib.parse import urlsplit
import redis
from backend.config import Settings
from backend.services.trader_provisioning import provision_trader_identity
from scripts.verify_schema import db_connect


def main():
    settings=Settings.from_env()
    if not settings.postgres_db.startswith(('tradegraph_test_','tradegraph_registration_')):
        raise ValueError('Isolated test database required')
    emails=json.load(sys.stdin)
    if not isinstance(emails,list) or len(emails)>100 or any(not isinstance(e,str) or not e.startswith('browser-live-') or not e.endswith('@example.test') for e in emails):
        raise ValueError('Only scoped browser fixture identities accepted')
    with db_connect() as connection:
        rows=connection.execute('''SELECT u.email,u.id,t.id,r.status FROM public.user_account u
          JOIN public.trader t ON t.user_account_id=u.id JOIN public.registration_state r ON r.user_account_id=u.id
          WHERE u.email=ANY(%s) ORDER BY u.email''',(emails,)).fetchall()
    if sys.argv[1] in ('redis-stop','redis-start'):
        root=Path(settings.trader_credentials_file).parent
        target=urlsplit(settings.redis_url)
        if target.hostname!='127.0.0.1' or target.port not in (6391,6392):raise ValueError('Scoped test Redis only')
        if sys.argv[1]=='redis-stop':
            client=redis.Redis.from_url(settings.redis_url)
            if client.info('server')['process_id']!=int((root/'redis.pid').read_text()):raise ValueError('Redis PID mismatch')
            client.shutdown(save=True)
        else:
            subprocess.run(['redis-server','--bind','127.0.0.1','--port',str(target.port),'--dir',str(root),'--appendonly','yes','--daemonize','yes','--pidfile',str(root/'redis.pid'),'--logfile',str(root/'redis.log')],check=True)
        print(json.dumps({'controlled_dependency':sys.argv[1]}));return
    if sys.argv[1]=='provision':
        for email,uid,tid,status in rows:provision_trader_identity(tid,settings,expected_database=settings.postgres_db)
        print(json.dumps({'verified':len(rows)}));return
    if sys.argv[1]!='snapshot':raise ValueError('Invalid fixture command')
    result=[]
    with db_connect() as connection:
        for email,uid,tid,status in rows:
            cash,escrow,tier=connection.execute('SELECT m.cash_balance,m.escrow_balance,f.tier_name FROM margin_account m JOIN fee_tier f ON f.id=m.fee_tier_id WHERE trader_id=%s',(tid,)).fetchone()
            positions=connection.execute('SELECT instrument_id,net_quantity,realized_pnl FROM position WHERE trader_id=%s ORDER BY instrument_id',(tid,)).fetchall()
            orders=connection.execute('SELECT id,status,filled_quantity,quantity FROM public."order" WHERE trader_id=%s ORDER BY id',(tid,)).fetchall()
            result.append({'email':email,'trader_id':str(tid),'status':status,'cash_balance':str(cash),'escrow_balance':str(escrow),'fee_tier':tier,'positions':[{'instrument_id':i,'net_quantity':str(q),'realized_pnl':str(p)} for i,q,p in positions],'orders':[{'id':str(i),'status':s,'filled_quantity':str(f),'quantity':str(q)} for i,s,f,q in orders]})
    print(json.dumps(result))


if __name__=='__main__':main()
