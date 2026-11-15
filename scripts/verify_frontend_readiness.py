#!/usr/bin/env python3
"""Read-only native/API readiness checks. Never starts an app or provisions data."""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx
import redis
from neo4j import GraphDatabase

from backend.config import Settings
from backend.stores.postgres import Database
from scripts.seed_live_bots import load_bot_specs, inspect_existing_bots
from scripts.verify_schema import EXPECTED_TABLES, db_connect

CATALOG_FIELDS = {'id':'integer','symbol':'string','tick_size':'integer',
                  'lot_size':'integer','is_active':'boolean'}
SIMULATOR_ROUTES = (('/admin/simulator/start','post'),
                    ('/admin/simulator/stop','post'),('/admin/simulator/status','get'))


def _read_only(conn, timeout):
    conn.read_only = True
    # Session-local timeout, not a persistent write. All application SQL is SELECT.
    conn.execute("SELECT set_config('statement_timeout',%s,true)", (str(int(timeout*1000)),))


def probe_postgres(settings, timeout):
    with Database(settings).connect() as conn:
        _read_only(conn, timeout)
        conn.execute('SELECT 1').fetchone()
        tables = {r['tablename'] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
        foreign_keys = conn.execute("SELECT count(*) AS n FROM pg_constraint WHERE contype='f' AND connamespace='public'::regnamespace").fetchone()['n']
        extensions = {r['extname'] for r in conn.execute("SELECT extname FROM pg_extension WHERE extname IN ('vector','pgcrypto')")}
        instruments = conn.execute('SELECT id,symbol,tick_size,lot_size FROM instrument WHERE is_active = TRUE ORDER BY symbol,id').fetchall()
        active = conn.execute('SELECT count(*) AS n FROM public."order" WHERE status IN (\'OPEN\',\'PARTIAL\')').fetchone()['n']
    valid = bool(instruments) and all(type(r['id']) is int and 0 < r['id'] < 2**31
        and isinstance(r['symbol'],str) and r['symbol'].strip()
        and type(r['tick_size']) is int and r['tick_size'] > 0
        and type(r['lot_size']) is int and r['lot_size'] > 0 for r in instruments)
    return dict(schema='valid' if tables == EXPECTED_TABLES and foreign_keys == 18
                and extensions == {'vector','pgcrypto'} else 'invalid',
                active_instruments=len(instruments), instrument_metadata_valid=bool(valid), active_orders=active)


def probe_bots(timeout):
    with db_connect() as conn:
        _read_only(conn, timeout)
        rows = inspect_existing_bots(conn, load_bot_specs())
    return sum(row is not None for row in rows.values())


def probe_redis(settings, timeout):
    client = redis.Redis.from_url(settings.redis_url,socket_connect_timeout=timeout,socket_timeout=timeout)
    try:
        if not client.ping():
            raise RuntimeError('Redis did not acknowledge PING')
    finally:
        client.close()


def probe_neo4j(settings, timeout):
    with GraphDatabase.driver(settings.neo4j_uri,auth=(settings.neo4j_user,settings.neo4j_password),
        connection_timeout=timeout,connection_acquisition_timeout=timeout,max_transaction_retry_time=0) as driver:
        driver.verify_connectivity()


def probe_api(api_base_url, timeout):
    with httpx.Client(timeout=timeout,follow_redirects=False) as client:
        health = client.get(api_base_url.rstrip('/')+'/health')
        health.raise_for_status()
        schema = client.get(api_base_url.rstrip('/')+'/openapi.json')
        schema.raise_for_status()
        return health.json(), schema.json()


def _typed_response(operation, schemas):
    ref = operation.get('responses',{}).get('200',{}).get('content',{}).get('application/json',{}).get('schema',{}).get('$ref','')
    prefix = '#/components/schemas/'
    return schemas.get(ref[len(prefix):]) if ref.startswith(prefix) else None


def run_checks(api_base_url, *, timeout=3):
    report = dict(ready_for_frontend=False,postgres='down',schema='not_checked',
        redis='down',neo4j='down',api='down',instrument_catalog='not_checked',
        active_instruments=0,bot_accounts_valid=0,simulator_api='not_checked',
        service_workers=None,active_orders=None,trading_ready=False,overall_health=None,
        derived_services={},warnings=[],failures=[])
    fail = report['failures'].append
    try:
        url = urlsplit(api_base_url)
        if (url.scheme not in ('http','https') or not url.hostname or url.username is not None
            or url.password is not None or url.query or url.fragment
            or (url.port is not None and not 0 < url.port < 65536)
            or type(timeout) not in (int,float) or not 0.1 <= timeout <= 10):
            raise ValueError('Invalid checker arguments')
        settings = Settings.from_env()
        if settings.service_workers != 1:
            raise ValueError('Only one worker permitted')
        report['service_workers'] = settings.service_workers
    except Exception:
        fail('INVALID_CONFIGURATION: Check backend settings, one worker, API URL and timeout (0.1–10s); credentials are never displayed.')
        return report
    try:
        result = probe_postgres(settings,timeout)
        report['postgres'] = 'up'
        report.update({k:v for k,v in result.items() if k != 'instrument_metadata_valid'})
        if result['schema'] != 'valid':
            fail('SCHEMA_MISMATCH: Expected the original 13-table set, 18 foreign keys and vector/pgcrypto extensions; run scripts/verify_schema.py.')
        if not result['instrument_metadata_valid']:
            fail('NO_VALID_ACTIVE_INSTRUMENTS: Verify active instrument IDs, symbols and positive tick/lot metadata; none will be inserted automatically.')
    except Exception:
        fail('POSTGRES_UNAVAILABLE: Check the configured runtime connection, native PostgreSQL service and read permissions.')
    try:
        report['bot_accounts_valid'] = probe_bots(timeout)
        if report['bot_accounts_valid'] != len(load_bot_specs()):
            fail('BOT_ACCOUNTS_MISSING: Run .venv/bin/python scripts/seed_live_bots.py --dry-run; provision explicitly if necessary.')
    except Exception:
        fail('BOT_ACCOUNTS_INVALID: Check administrative read access and identity associations with .venv/bin/python scripts/seed_live_bots.py --dry-run.')
    for name, probe in (('redis',probe_redis),('neo4j',probe_neo4j)):
        try:
            probe(settings,timeout)
            report[name] = 'up'
        except Exception:
            fail(name.upper()+'_UNAVAILABLE: Check the native service and its configured connection; no data was modified.')
    try:
        health, schema = probe_api(api_base_url,timeout)
        dependencies = health['dependencies']
        if (health['status'] not in ('ok','unhealthy') or type(health['trading_ready']) is not bool
            or not {'postgres','redis','neo4j'} <= set(dependencies)
            or any(v not in ('up','down') for v in dependencies.values())):
            raise ValueError('Invalid health response')
        report.update(api='up',trading_ready=health['trading_ready'],overall_health=health['status'],
            derived_services={k:v for k,v in dependencies.items() if k in ('redis','neo4j','regimes')})
        if health['status'] != 'ok' or not health['trading_ready'] or any(v != 'up' for v in dependencies.values()):
            fail('API_UNHEALTHY: Inspect /health; financial readiness and derived-service health are distinct.')
        paths, schemas = schema['paths'], schema['components']['schemas']
        operation = paths.get('/instruments',{}).get('get',{})
        catalog = _typed_response(operation,schemas) or {}
        items = catalog.get('properties',{}).get('items',{})
        item_ref = items.get('items',{}).get('$ref','')
        info = schemas.get(item_ref.removeprefix('#/components/schemas/'),{})
        properties = info.get('properties',{})
        if (items.get('type') == 'array' and set(properties) == set(CATALOG_FIELDS)
            and set(info.get('required',[])) == set(CATALOG_FIELDS)
            and all(properties[k].get('type') == kind for k,kind in CATALOG_FIELDS.items())
            and operation.get('security')):
            report['instrument_catalog'] = 'registered'
        else:
            report['instrument_catalog'] = 'invalid'
            fail('INSTRUMENT_CATALOG_INVALID: Verify authenticated GET /instruments and its typed active-instrument response in OpenAPI.')
        if all(_typed_response(paths.get(path,{}).get(method,{}),schemas) for path,method in SIMULATOR_ROUTES):
            report['simulator_api'] = 'registered'
        else:
            report['simulator_api'] = 'invalid'
            fail('SIMULATOR_API_INVALID: Verify all three typed simulator routes are registered; the checker will not start a session.')
    except Exception:
        fail('API_UNAVAILABLE: Start or inspect the existing single-worker FastAPI server and GET /health and /openapi.json; never start a competing owner.')
    if report['active_orders']:
        running = report['api'] == 'up' and report['trading_ready']
        report['warnings'].append('ACTIVE_ORDERS_BLOCK_COLD_RESTART: '+(
            'Active orders can be valid in the running exchange, but a cold restart refuses unresolved OPEN/PARTIAL orders.'
            if running else 'Unresolved OPEN/PARTIAL orders would prevent startup; operator reconciliation is required.')+
            ' Do not automatically cancel human orders or reset balances.')
    report['ready_for_frontend'] = not report['failures']
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-base-url',default='http://127.0.0.1:8000')
    parser.add_argument('--timeout',type=float,default=3,help='HTTP/Redis/Neo4j and SQL statement timeout, 0.1–10s; PostgreSQL connects retain existing bounded settings')
    parser.add_argument('--json',action='store_true',help='Machine-readable report without credentials')
    args = parser.parse_args(argv)
    report = run_checks(args.api_base_url,timeout=args.timeout)
    if args.json:
        print(json.dumps(report,indent=2))
    else:
        print('READY FOR FRONTEND' if report['ready_for_frontend'] else 'NOT READY FOR FRONTEND')
        for key,value in report.items():
            if key not in ('failures','warnings','ready_for_frontend'):
                print(f'{key}: {value}')
        for kind in ('warnings','failures'):
            for message in report[kind]:
                print(kind.upper()+': '+message)
    return 0 if report['ready_for_frontend'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
