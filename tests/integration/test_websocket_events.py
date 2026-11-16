from contextlib import ExitStack
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from backend.api.main import create_app
from tests.integration.test_order_pipeline import accounts,login,order
from tests.integration.test_polyglot import wait_until

ORIGIN='http://127.0.0.1:3000'


def ticket(client,headers):
    key=uuid4().hex*2
    response=client.post('/live/ticket',headers=headers,json={'session_key':key})
    assert response.status_code==200,response.text
    return response.json()['ticket'],key


def connect(client,value,origin=ORIGIN):
    return client.websocket_connect('/live/ws',headers={'Origin':origin},subprotocols=['tradegraph.v1','ticket.'+value])


def receive(ws,kind):
    for _ in range(30):
        event=ws.receive_json()
        if event['type']=='ping':ws.send_json({'type':'pong'})
        if event['type']==kind:return event
    raise AssertionError('Expected live event was not received')


def test_tickets_are_single_use_and_origins_and_subscriptions_are_restricted(accounts):
    users,iid=accounts
    with TestClient(create_app()) as client:
        headers=login(client,users[0])
        assert client.post('/live/ticket',json={'session_key':'a'*64}).status_code==401
        value,key=ticket(client,headers)
        with pytest.raises(WebSocketDisconnect):
            with connect(client,value,'https://evil.test'):pass
        # A hostile origin cannot consume the valid ticket.
        with connect(client,value) as ws:
            assert receive(ws,'resync.required')['schema_version']==1
            ws.send_json({'type':'subscribe','instrument_ids':[iid]})
            receive(ws,'resync.required')
            ws.send_json({'type':'subscribe','instrument_ids':[iid],'trader_id':str(users[1]['trader_id'])})
            with pytest.raises(WebSocketDisconnect):
                while True:ws.receive_json()
        with pytest.raises(WebSocketDisconnect):
            with connect(client,value):pass
        with pytest.raises(WebSocketDisconnect):
            with connect(client,'x'*43):pass
        value,_=ticket(client,headers)
        client.portal.call(client.app.state.live_tickets.client.delete,client.app.state.live_tickets.key(value))
        with pytest.raises(WebSocketDisconnect):
            with connect(client,value):pass
        value,key=ticket(client,headers)
        assert client.post('/live/revoke',headers=headers,json={'session_key':key}).status_code==200
        with pytest.raises(WebSocketDisconnect):
            with connect(client,value):pass


def test_committed_trade_private_invalidation_and_connection_limits(accounts):
    users,iid=accounts
    with TestClient(create_app()) as client:
        a,b=login(client,users[0]),login(client,users[1])
        ta,_=ticket(client,a);tb,_=ticket(client,b)
        with connect(client,ta) as wa,connect(client,tb) as wb:
            for ws in (wa,wb):
                receive(ws,'resync.required')
                ws.send_json({'type':'subscribe','instrument_ids':[iid]})
                receive(ws,'resync.required')
            sell=client.post('/orders',headers=b,json=order(iid,'SELL',100,1))
            buy=client.post('/orders',headers=a,json=order(iid,'BUY',100,1))
            assert sell.status_code==buy.status_code==201
            for ws in (wa,wb):
                event=receive(ws,'trade.committed')
                assert event['instrument_id']==iid and event['execution_id'].isdigit()
                rows=client.app.state.database.query('SELECT id FROM execution WHERE id=%s',(int(event['execution_id']),))
                assert len(rows)==1  # notification can never precede COMMIT
                assert receive(ws,'account.changed')['sequence']>event['sequence']
            with ExitStack() as stack:
                for _ in range(3):
                    value,_=ticket(client,a)
                    stack.enter_context(connect(client,value))
                value,_=ticket(client,a)
                with pytest.raises(WebSocketDisconnect):
                    with connect(client,value):pass
        wait_until(lambda:len(client.app.state.live_bus.clients),lambda n:n==0)


def test_revocation_disconnects_an_already_connected_socket(accounts):
    users,_=accounts
    with TestClient(create_app()) as client:
        headers=login(client,users[0])
        value,key=ticket(client,headers)
        with connect(client,value) as ws:
            receive(ws,'resync.required')
            assert client.post('/live/revoke',headers=headers,json={'session_key':key}).status_code==200
            with pytest.raises(WebSocketDisconnect):
                for _ in range(3):
                    event=ws.receive_json()
                    if event['type']=='ping':ws.send_json({'type':'pong'})
        wait_until(lambda:len(client.app.state.live_bus.clients),lambda n:n==0)
