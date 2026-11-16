"""Real HTTP BFF checks; existing scoped synthetic fixtures, no second API owner.
Run only with one native FastAPI and one Next.js server already running.
"""
import httpx
import pytest
from tests.integration.test_order_pipeline import accounts

ORIGIN = 'http://127.0.0.1:3000'
HEADERS = {'Origin': ORIGIN, 'X-TradeGraph-Request': '1', 'Content-Type': 'application/json'}


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


def test_real_resting_partial_fill_and_cancellation(accounts):
    import time
    from uuid import uuid4
    users, instrument = accounts
    orders = []
    with httpx.Client(base_url=ORIGIN, timeout=40) as buyer, httpx.Client(base_url=ORIGIN, timeout=40) as seller:
        assert signin(buyer, users[0]).status_code == 200
        assert signin(seller, users[1]).status_code == 200
        symbol = next(i['symbol'] for i in buyer.get('/api/backend/instruments').json()['items'] if i['id'] == instrument)
        def submit(client, side, price, qty, key=None):
            r = client.post('/api/backend/orders', headers=HEADERS | {'Idempotency-Key': key or str(uuid4())}, json={'instrument_id': instrument, 'side': side, 'price_ticks': str(price), 'quantity': str(qty)})
            if r.status_code == 200: orders.append((client, r.json()['order_id']))
            return r
        def wait_for(read, predicate):
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                value = read()
                if predicate(value): return value
                time.sleep(.1)
            raise AssertionError('Authoritative state did not converge within 8 seconds')
        try:
            key = str(uuid4())
            resting = submit(seller, 'SELL', 100, 3, key)
            assert resting.status_code == 200
            assert submit(seller, 'SELL', 100, 3, key).status_code == 409
            assert submit(buyer, 'BUY', 1000000, 1).status_code == 409
            assert submit(buyer, 'BUY', 0, 1).status_code == 422
            book = wait_for(lambda: buyer.get(f'/api/backend/market/{symbol}/book').json(), lambda x: x.get('asks') == [{'price_ticks': '100', 'quantity': '3'}])
            assert book['asks'][0]['quantity'] == '3'
            assert buyer.get(f'/api/backend/market/{symbol}/trades').json()['items'] == []
            crossing = submit(buyer, 'BUY', 105, 1)
            assert crossing.status_code == 200
            trades = wait_for(lambda: buyer.get(f'/api/backend/market/{symbol}/trades').json()['items'], lambda x: len(x) == 1)
            assert trades[0]['price_ticks'] == '100' and trades[0]['quantity'] == '1'
            assert trades[0]['buy_order_id'] == crossing.json()['order_id']
            seller_orders = seller.get('/api/backend/orders/me?limit=1').json()
            row = seller_orders['items'][0]
            assert row['status'] == 'PARTIAL' and row['filled_quantity'] == '1' and row['quantity'] == '3'
            assert seller_orders['next_before_id'] == row['id']
            assert seller.get(f"/api/backend/orders/me?before_id={row['id']}").json()['items'] == []
            assert buyer.get('/api/backend/orders/me').json()['items'][0]['status'] == 'FILLED'
            assert buyer.get('/api/backend/account/me').json()['escrow_balance'] == '0'
            cancelled = seller.post(f"/api/backend/orders/{row['id']}/cancel", headers=HEADERS, json=None)
            assert cancelled.status_code == 200 and cancelled.json()['cancelled_quantity'] == '2'
            assert seller.get('/api/backend/account/me').json()['escrow_balance'] == '0'
            wait_for(lambda: buyer.get(f'/api/backend/market/{symbol}/book').json(), lambda x: x.get('asks') == [])
            analytics = buyer.get(f'/api/backend/market/{symbol}/analytics?lower_ticks=95&upper_ticks=105').json()
            assert analytics['vwap_ticks'] == '100' and analytics['band_volume'] == '1'
        finally:
            for client, order_id in orders:
                client.post(f'/api/backend/orders/{order_id}/cancel', headers=HEADERS, json=None)
