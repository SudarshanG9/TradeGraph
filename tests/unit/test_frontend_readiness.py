"""Failure classification and safety boundaries; native readiness is tested separately."""
from types import SimpleNamespace
from unittest.mock import MagicMock
import json

import pytest

from scripts import verify_frontend_readiness as checker


def openapi():
    info = dict(type='object',required=list(checker.CATALOG_FIELDS),properties={
        k:dict(type=v) for k,v in checker.CATALOG_FIELDS.items()})
    schemas = dict(InstrumentInfo=info,InstrumentCatalog=dict(properties=dict(items=dict(type='array',items={'$ref':'#/components/schemas/InstrumentInfo'}))),SimulationStatus=dict(type='object'))
    def operation(name):
        return dict(security=[{'HTTPBearer':[]}],responses={'200':{'content':{'application/json':{'schema':{'$ref':'#/components/schemas/'+name}}}}})
    paths={'/instruments':{'get':operation('InstrumentCatalog')}}
    for path,method in checker.SIMULATOR_ROUTES:paths[path]={method:operation('SimulationStatus')}
    return dict(paths=paths,components=dict(schemas=schemas))


@pytest.fixture
def healthy(monkeypatch):
    monkeypatch.setattr(checker.Settings,'from_env',lambda:SimpleNamespace(service_workers=1))
    monkeypatch.setattr(checker,'probe_postgres',lambda *a:dict(schema='valid',active_instruments=3,instrument_metadata_valid=True,active_orders=0))
    monkeypatch.setattr(checker,'probe_bots',lambda *a:8)
    monkeypatch.setattr(checker,'probe_redis',lambda *a:None)
    monkeypatch.setattr(checker,'probe_neo4j',lambda *a:None)
    health=dict(status='ok',trading_ready=True,dependencies=dict(postgres='up',redis='up',neo4j='up',regimes='up'))
    monkeypatch.setattr(checker,'probe_api',lambda *a:(health,openapi()))
    return health


def test_healthy_report_and_cli_exit(healthy,capsys):
    assert checker.main(['--json'])==0
    report=json.loads(capsys.readouterr().out)
    assert report['ready_for_frontend'] and report['bot_accounts_valid']==8
    assert report['instrument_catalog']==report['simulator_api']=='registered'
    assert report['warnings']==report['failures']==[]


@pytest.mark.parametrize('probe', ['probe_postgres','probe_bots','probe_redis','probe_neo4j','probe_api'])
def test_unavailable_dependencies_fail_without_leaking_exceptions(healthy,monkeypatch,capsys,probe):
    def broken(*args):raise RuntimeError('SECRET-password-and-internal-config')
    monkeypatch.setattr(checker,probe,broken)
    assert checker.main(['--json'])==1
    output=capsys.readouterr().out
    assert 'SECRET' not in output and not json.loads(output)['ready_for_frontend']


def test_missing_bots_no_instruments_and_schema_drift(healthy,monkeypatch):
    monkeypatch.setattr(checker,'probe_bots',lambda *a:7)
    monkeypatch.setattr(checker,'probe_postgres',lambda *a:dict(schema='invalid',active_instruments=0,instrument_metadata_valid=False,active_orders=0))
    report=checker.run_checks('http://localhost:8000')
    assert not report['ready_for_frontend'] and len(report['failures'])==3
    assert '--dry-run' in report['failures'][-1]


@pytest.mark.parametrize('api_up', [True,False])
def test_active_orders_are_warning_not_a_destructive_recovery(healthy,monkeypatch,api_up):
    monkeypatch.setattr(checker,'probe_postgres',lambda *a:dict(schema='valid',active_instruments=3,instrument_metadata_valid=True,active_orders=2))
    if not api_up:
        monkeypatch.setattr(checker,'probe_api',lambda *a:(_ for _ in ()).throw(ConnectionError()))
    report=checker.run_checks('http://localhost:8000')
    assert len(report['warnings'])==1 and report['ready_for_frontend']==api_up
    assert ('running exchange' in report['warnings'][0])==api_up


@pytest.mark.parametrize('kwargs', [dict(api_base_url='http://user:SECRET@localhost'),dict(api_base_url='file:///etc/passwd'),dict(api_base_url='https://localhost?token=SECRET'),dict(timeout=0),dict(timeout=float('nan'))])
def test_invalid_checker_arguments(healthy,kwargs):
    report=checker.run_checks(**(dict(api_base_url='http://localhost:8000')|kwargs))
    assert not report['ready_for_frontend'] and 'SECRET' not in repr(report)


def test_invalid_backend_configuration_is_sanitized(healthy,monkeypatch):
    monkeypatch.setattr(checker.Settings,'from_env',lambda:(_ for _ in ()).throw(ValueError('SECRET')))
    report=checker.run_checks('http://localhost:8000')
    assert not report['ready_for_frontend'] and 'SECRET' not in repr(report)


def test_unhealthy_financial_and_derived_status_are_distinct(healthy):
    healthy.update(status='unhealthy',trading_ready=True)
    healthy['dependencies']['redis']='down'
    report=checker.run_checks('http://localhost:8000')
    assert not report['ready_for_frontend'] and report['trading_ready']
    assert report['derived_services']['redis']=='down' and report['api']=='up'


def test_missing_or_untyped_routes_fail(healthy,monkeypatch):
    schema=openapi();schema['paths']['/instruments']['get']['responses']={}
    del schema['paths']['/admin/simulator/stop']
    monkeypatch.setattr(checker,'probe_api',lambda *a:(healthy,schema))
    result=checker.run_checks('http://localhost:8000')
    assert not result['ready_for_frontend']
    assert result['instrument_catalog']==result['simulator_api']=='invalid'


def test_sql_probes_are_forced_read_only_and_issue_only_selects(monkeypatch):
    conn=MagicMock();conn.__enter__.return_value=conn
    def execute(sql,params=()):
        assert conn.read_only is True
        assert sql.lstrip().upper().startswith('SELECT')
        if 'pg_tables' in sql:return [dict(tablename=t) for t in checker.EXPECTED_TABLES]
        if 'pg_constraint' in sql:return SimpleNamespace(fetchone=lambda:dict(n=18))
        if 'pg_extension' in sql:return [dict(extname=e) for e in ('vector','pgcrypto')]
        if 'FROM instrument' in sql:return SimpleNamespace(fetchall=lambda:[dict(id=1,symbol='ACME',tick_size=1,lot_size=1)])
        if 'FROM public."order"' in sql:return SimpleNamespace(fetchone=lambda:dict(n=0))
        return MagicMock()
    conn.execute.side_effect=execute
    monkeypatch.setattr(checker,'Database',lambda s:SimpleNamespace(connect=lambda:conn))
    assert checker.probe_postgres(object(),1)['schema']=='valid'
    monkeypatch.setattr(checker,'db_connect',lambda:conn)
    def inspect(c,specs):
        assert c.read_only is True
        return {s.email:object() for s in specs}
    monkeypatch.setattr(checker,'inspect_existing_bots',inspect)
    assert checker.probe_bots(1)==8


def test_network_probes_only_ping_connect_and_http_get(monkeypatch):
    settings=SimpleNamespace(redis_url='redis://localhost',neo4j_uri='bolt://localhost',neo4j_user='test',neo4j_password='SECRET')
    cache=MagicMock();monkeypatch.setattr(checker.redis.Redis,'from_url',lambda *a,**k:cache)
    checker.probe_redis(settings,1)
    assert [call[0] for call in cache.method_calls]==['ping','close']
    driver=MagicMock();driver.__enter__.return_value=driver
    monkeypatch.setattr(checker.GraphDatabase,'driver',lambda *a,**k:driver)
    checker.probe_neo4j(settings,1)
    assert [call[0] for call in driver.method_calls]==['verify_connectivity']
    http=MagicMock();http.__enter__.return_value=http
    monkeypatch.setattr(checker.httpx,'Client',lambda **k:http)
    checker.probe_api('http://localhost:8000',1)
    assert [c.args[0] for c in http.get.call_args_list]==['http://localhost:8000/health','http://localhost:8000/openapi.json']
    assert not http.post.called
