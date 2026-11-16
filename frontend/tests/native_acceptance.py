"""Real HTTP BFF checks; existing scoped synthetic fixtures, no second API owner.
Run only with one native FastAPI and one Next.js server already running.
"""
import httpx
import pytest
from tests.integration.test_order_pipeline import accounts

ORIGIN = 'http://127.0.0.1:3000'
HEADERS = {'Origin': ORIGIN, 'X-TradeGraph-Request': '1'}


def signin(client, user, selected=None):
    return client.post('/api/backend/login', headers=HEADERS | {'X-TradeGraph-Role': selected or user['role']},
                       json={k: user[k] for k in ('email', 'password')})


def test_real_authentication_and_role_boundaries(accounts):
    users, _ = accounts
    with httpx.Client(base_url=ORIGIN, timeout=40) as client:
        assert client.get('/api/backend/account/me').status_code == 401
        assert 'url=/auth?reason=expired' in client.get('/trader/dashboard').text
        assert client.post('/api/backend/login', json={'email': 'missing@example.test', 'password': 'invalid'}).status_code == 403
        assert client.post('/api/backend/login', headers=HEADERS, json={'email': 'missing@example.test', 'password': 'invalid'}).status_code == 401
        assert signin(client, users[3], 'TRADER').status_code == 403
        for user, own, forbidden in [(users[0], '/trader/dashboard', '/admin/overview'), (users[3], '/admin/overview', '/trader/dashboard')]:
            response = signin(client, user)
            assert response.status_code == 200
            assert set(response.json()) == {'kind', 'role', 'expiresAt'}
            assert response.json()['role'] == user['role']
            cookie = response.headers['set-cookie'].lower()
            assert 'httponly' in cookie and 'samesite=strict' in cookie
            assert 'access_token' not in response.text
            assert client.get(own).status_code == 200
            assert 'url=/auth?reason=forbidden' in client.get(forbidden).text
            path = '/api/backend/admin/desks/rollup' if user['role'] == 'TRADER' else '/api/backend/account/me'
            assert client.get(path).status_code == 403
            assert client.get('/api/backend/instruments').status_code == 200
            assert client.post('/api/session', headers={'Origin': 'https://evil.test', 'X-TradeGraph-Request': '1'}).status_code == 403
            assert client.post('/api/session', headers=HEADERS).status_code == 200
            assert client.get('/api/session').json() is None
            assert client.get('/api/backend/instruments').status_code == 401


def test_live_catalog_and_account(accounts):
    users, instrument = accounts
    with httpx.Client(base_url=ORIGIN, timeout=40) as client:
        assert signin(client, users[0]).status_code == 200
        catalog = client.get('/api/backend/instruments')
        assert catalog.status_code == 200
        metadata = next(i for i in catalog.json()['items'] if i['id'] == instrument)
        assert metadata['is_active'] is True
        assert metadata['tick_size'] == '1' and metadata['lot_size'] == '1'
        account = client.get('/api/backend/account/me')
        assert account.status_code == 200
        assert account.json() == {'trader_id': str(users[0]['trader_id']), 'cash_balance': '20000', 'escrow_balance': '0', 'positions': []}
