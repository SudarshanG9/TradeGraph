"""Real authenticated catalog reads; only fixture instruments are created/removed."""
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from backend.api.main import create_app
from backend.api.routes.instruments import CATALOG_SQL
from scripts.verify_schema import db_connect
from tests.integration.test_order_pipeline import accounts, login
from tests.integration.test_polyglot import wait_until


@pytest.fixture
def catalog_instruments():
    prefix = 'CAT' + uuid4().hex[:10]
    with db_connect() as conn:
        ids = [conn.execute('''INSERT INTO instrument(symbol,tick_size,lot_size,is_active)
            VALUES (%s,%s,%s,%s) RETURNING id''', values).fetchone()[0]
            for values in ((prefix+'Z',5,10,True),(prefix+'A',10,5,True),(prefix+'X',1,1,False))]
    try:
        yield ids
    finally:
        with db_connect() as conn:
            conn.execute('DELETE FROM instrument WHERE id=ANY(%s)', (ids,))


def test_authenticated_catalog_matches_postgres_and_preserves_state(accounts, catalog_instruments):
    users, _ = accounts
    with db_connect() as conn:
        before = conn.execute('SELECT * FROM instrument ORDER BY id').fetchall()
        expected = conn.execute(CATALOG_SQL).fetchall()
    with TestClient(create_app()) as client:
        assert client.get('/instruments').status_code == 401
        headers = [login(client,users[i]) for i in (0,3)]
        results = [client.get('/instruments',headers=h) for h in headers]
        assert all(r.status_code == 200 for r in results)
        assert results[0].json() == results[1].json()
        items = results[0].json()['items']
        assert [tuple(r[k] for k in ('id','symbol','tick_size','lot_size','is_active')) for r in items] == expected
        assert all(set(r) == {'id','symbol','tick_size','lot_size','is_active'} and r['is_active'] for r in items)
        assert catalog_instruments[2] not in {r['id'] for r in items}
        assert set(catalog_instruments[:2]) <= {r['id'] for r in items}
        assert client.get('/instruments',headers=headers[0]).json() == results[0].json()
        schema = client.get('/openapi.json').json()
        route = schema['paths']['/instruments']['get']
        assert route['responses']['200']['content']['application/json']['schema']['$ref'].endswith('/InstrumentCatalog')
        assert route['security'] == [{'HTTPBearer': []}]
        own = next(r for r in items if r['id']==catalog_instruments[0])
        book = wait_until(lambda:client.get('/market/'+own['symbol']+'/book',headers=headers[0]).json(),lambda r:r.get('as_of') is not None)
        assert book['symbol']==own['symbol'] and book['bids']==book['asks']==[]
    with db_connect() as conn:
        assert conn.execute('SELECT * FROM instrument ORDER BY id').fetchall() == before


def test_empty_catalog_never_fabricates_an_instrument(accounts, monkeypatch):
    users, _ = accounts
    with TestClient(create_app()) as client:
        original = client.app.state.database.query
        def scoped_query(sql, params=()):
            # Exercise a native empty result without changing global demo metadata.
            if sql == CATALOG_SQL:
                sql = sql.replace('WHERE is_active = TRUE', 'WHERE is_active = TRUE AND FALSE')
            return original(sql,params)
        monkeypatch.setattr(client.app.state.database,'query',scoped_query)
        for user in (users[0],users[3]):
            result = client.get('/instruments',headers=login(client,user))
            assert result.status_code == 200 and result.json() == {'items':[]}
