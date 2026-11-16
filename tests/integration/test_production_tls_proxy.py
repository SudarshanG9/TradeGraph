"""Real Caddy validator, production Next BFF and Uvicorn over trusted test TLS.

Run with TRADEGRAPH_CADDY pointing to a real binary and an isolated test environment.
The test certificate is trusted explicitly; TLS verification is never disabled.
"""
import asyncio
import json
import os
import time
import pytest
import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus, ConnectionClosed
from scripts.production_test_stack import ProductionTestStack
from tests.integration.test_order_pipeline import accounts
from backend.auth.websocket_ticket import TicketStore
from backend.config import Settings


@pytest.fixture
def tls_stack(accounts):
    binary=os.environ.get('TRADEGRAPH_CADDY')
    if not binary:
        pytest.skip('Set TRADEGRAPH_CADDY for actual TLS integration; never a mock proxy')
    with ProductionTestStack(binary,root=os.environ.get('TRADEGRAPH_TEST_ARTIFACTS')) as stack:
        yield stack


def signin(client,stack,user):
    response=client.post(stack.origin+'/api/backend/login',headers={'Origin':stack.origin,'X-TradeGraph-Request':'1'},
                         json={k:user[k] for k in ('email','password')})
    assert response.status_code==200,response.text
    assert 'access_token' not in response.text
    return response


def issue(client,stack):
    response=client.post(stack.origin+'/api/live/ticket',headers={'Origin':stack.origin,'X-TradeGraph-Request':'1'})
    assert response.status_code==200,response.text
    return response.json()['ticket']


async def wss(stack,ticket,**kwargs):
    return await connect(stack.origin.replace('https:','wss:')+'/live/ws',ssl=stack.ssl,
                         origin=stack.origin,subprotocols=['tradegraph.v1','ticket.'+ticket],**kwargs)


async def rejected(stack,ticket,**kwargs):
    with pytest.raises(InvalidStatus):
        socket=await wss(stack,ticket,**kwargs)
        await socket.close()


def test_real_tls_bff_and_ticket_security(tls_stack,accounts):
    stack=tls_stack;users,_=accounts
    with httpx.Client(verify=stack.ssl,trust_env=False,timeout=15) as client:
        redirect=client.get(stack.http_origin+'/api/session')
        assert redirect.status_code in (301,302,307,308)
        assert redirect.headers['location']==stack.origin+'/api/session'
        response=signin(client,stack,users[0])
        cookie=response.headers['set-cookie']
        assert all(value in cookie.lower() for value in ('secure','httponly','samesite=strict'))
        assert client.get(stack.origin+'/api/session').json()['role']=='TRADER'
        assert client.post(stack.origin+'/api/live/ticket',headers={'Origin':'https://evil.test','X-TradeGraph-Request':'1'}).status_code==403
        assert client.get(stack.origin+'/orders/me').status_code==404  # no direct backend routes
        assert client.get(stack.origin+'/api/backend/orders/me').status_code==200
        valid=issue(client,stack)
        async def exercise():
            socket=await wss(stack,valid,additional_headers={'Cookie':'must-not-forward-cookie','Authorization':'Bearer must-not-forward-token'})
            assert socket.subprotocol=='tradegraph.v1'
            assert 'ticket.' not in str(socket.response.headers)
            frames=[]
            while len(frames)<2:
                frame=json.loads(await asyncio.wait_for(socket.recv(),5));frames.append(frame)
                if frame['type']=='ping':await socket.send(json.dumps({'type':'pong'}))
            await socket.close()
            await rejected(stack,valid)  # single use
            await rejected(stack,'x'*43)
        asyncio.run(exercise())
        expired=issue(client,stack)
        # Real Redis expiry, shortened only in the isolated namespace.
        async def expire():
            settings=Settings.from_env();store=TicketStore(settings.redis_url,settings.postgres_db)
            try:await store.client.pexpire(store.key(expired),1)
            finally:await store.close()
        asyncio.run(expire());time.sleep(.02)
        asyncio.run(rejected(stack,expired))
        active=issue(client,stack)
        async def logout():
            socket=await wss(stack,active)
            response=await asyncio.to_thread(client.post,stack.origin+'/api/session',headers={'Origin':stack.origin,'X-TradeGraph-Request':'1'})
            assert response.status_code==200
            with pytest.raises(ConnectionClosed):
                while True:
                    frame=json.loads(await asyncio.wait_for(socket.recv(),15))
                    if frame['type']=='ping':await socket.send(json.dumps({'type':'pong'}))
        asyncio.run(logout())
        assert client.get(stack.origin+'/api/session').json() is None
    forwarded=[json.loads(line) for line in (stack.root/'upstream-headers.jsonl').read_text().splitlines()]
    assert forwarded and all(not r['cookie'] and not r['authorization'] and r['ticket_offered'] for r in forwarded)
    logs=(stack.root/'proxy.log').read_text()
    assert valid not in logs and expired not in logs and active not in logs
    assert 'must-not-forward-cookie' not in logs and 'must-not-forward-token' not in logs
