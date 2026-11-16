"""Authenticated notification channel. No financial mutations are accepted here."""
import asyncio
import anyio
import json
import time
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from backend.api.dependencies import actor
from backend.auth.security import decode_token
from backend.events.live_protocol import Subscription

router=APIRouter(prefix='/live')


class TicketRequest(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    session_key: str=Field(pattern=r'^[a-f0-9]{64}$')


@router.post('/ticket')
async def issue_ticket(body: TicketRequest,request: Request,identity=Depends(actor)):
    claims=decode_token(request.headers['authorization'].split(' ',1)[1],request.app.state.settings)
    try:ticket=await request.app.state.live_tickets.issue(identity,body.session_key,claims['exp'])
    except Exception:raise HTTPException(503,detail='LIVE_AUTH_UNAVAILABLE') from None
    return {'ticket':ticket,'expires_in':20,'path':'/live/ws'}


@router.post('/revoke')
async def revoke(body: TicketRequest,request: Request,identity=Depends(actor)):
    claims=decode_token(request.headers['authorization'].split(' ',1)[1],request.app.state.settings)
    try:await request.app.state.live_tickets.revoke(body.session_key,claims['exp'])
    except Exception:raise HTTPException(503,detail='LIVE_AUTH_UNAVAILABLE') from None
    return {'revoked':True}


def trusted_origin(settings):
    value=settings.app_origin
    try:
        parsed=urlsplit(value)
        valid=parsed.scheme in ('http','https') and parsed.netloc and not parsed.username and not parsed.password and not parsed.query and not parsed.fragment and parsed.path in ('','/')
        loopback=parsed.hostname in ('localhost','127.0.0.1','::1')
        if not valid or (parsed.scheme=='http' and not (loopback and settings.allow_insecure_loopback_origin)):
            raise ValueError()
        return value.rstrip('/')
    except ValueError:raise ValueError('APP_ORIGIN_CONFIGURATION_INVALID') from None


@router.websocket('/ws')
async def live_socket(socket: WebSocket):
    state=socket.app.state
    try:
        if socket.headers.get('origin')!=trusted_origin(state.settings):raise ValueError()
        protocols=socket.scope.get('subprotocols',[])
        tickets=[p[7:] for p in protocols if p.startswith('ticket.')]
        if 'tradegraph.v1' not in protocols or len(tickets)!=1:raise ValueError()
        claim=await state.live_tickets.consume(tickets[0])
        if not claim:raise ValueError()
        identity=await asyncio.to_thread(state.database.identity,claim['subject'])
        if not identity or identity['role']!=claim['role']:raise ValueError()
        registration=await asyncio.to_thread(state.database.registration_status,claim['subject'])
        if registration is not None and registration!='ACTIVE':raise ValueError()
        client=state.live_bus.connect(identity)
    except Exception:
        await socket.close(code=1008)
        return
    await socket.accept(subprotocol='tradegraph.v1')  # never reflect the credential
    last_seen=time.monotonic()
    async def receive():
        nonlocal last_seen
        window=time.monotonic();messages=0
        while True:
            raw=await socket.receive_text()
            if len(raw)>1024:raise ValueError('Message too large')
            now=time.monotonic()
            if now-window>=10:window=now;messages=0
            messages+=1
            if messages>30:raise ValueError('Message rate exceeded')
            body=Subscription.model_validate_json(raw)
            last_seen=now
            if body.type=='pong':continue
            if any(type(i) is not int or not 0<i<2**31 for i in body.instrument_ids):raise ValueError('Invalid instrument')
            if body.type=='subscribe':
                known=await asyncio.to_thread(state.database.query,'SELECT id FROM instrument WHERE is_active AND id=ANY(%s)',(body.instrument_ids,))
                ids={r['id'] for r in known}
                if ids!=set(body.instrument_ids) or len(client.instruments|ids)>8:raise ValueError('Invalid subscription')
                client.instruments.update(ids)
                state.live_bus.send(client,'resync.required')
            else:client.instruments.difference_update(body.instrument_ids)
    async def send():
        next_check=0
        while True:
            if client.overflow:
                await socket.close(code=1013);return
            if time.monotonic()>=next_check:
                if claim['expires_at']<=time.time() or await state.live_tickets.revoked(claim['session_key']):
                    await socket.close(code=1008);return
                current=await asyncio.to_thread(state.database.identity,claim['subject'])
                status=await asyncio.to_thread(state.database.registration_status,claim['subject'])
                if not current or current['role']!=claim['role'] or (status is not None and status!='ACTIVE'):
                    await socket.close(code=1008);return
                if time.monotonic()-last_seen>45:
                    await socket.close(code=1001);return
                await socket.send_json({'type':'ping'})
                next_check=time.monotonic()+10
            try:event=await asyncio.wait_for(client.queue.get(),timeout=1)
            except asyncio.TimeoutError:continue
            await asyncio.wait_for(socket.send_json(event),timeout=5)
    tasks=[asyncio.create_task(receive()),asyncio.create_task(send())]
    state.live_socket_tasks.update(tasks)
    try:
        await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
    except asyncio.CancelledError:
        pass
    finally:
        state.live_bus.disconnect(client)
        for task in tasks:task.cancel()
        with anyio.CancelScope(shield=True):
            await asyncio.gather(*tasks,return_exceptions=True)
            state.live_socket_tasks.difference_update(tasks)
            try:await socket.close(code=1008)
            except (RuntimeError,WebSocketDisconnect):pass
