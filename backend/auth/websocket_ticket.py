"""Redis single-use 20-second credentials, scoped to identity/session/expiry."""
import hashlib
import json
import secrets
import time
import redis.asyncio as redis


class TicketStore:
    def __init__(self,url,database):
        self.client=redis.Redis.from_url(url,decode_responses=True,socket_connect_timeout=2,socket_timeout=2)
        self.prefix='tradegraph:live:'+database+':'

    def key(self,ticket):
        return self.prefix+'ticket:'+hashlib.sha256(ticket.encode()).hexdigest()

    async def issue(self,identity,session_key,expires_at):
        if expires_at<=time.time():raise ValueError('Expired identity')
        ticket=secrets.token_urlsafe(32)
        claim={'subject':str(identity['id']),'role':identity['role'],'session_key':session_key,'expires_at':expires_at}
        if await self.revoked(session_key):raise ValueError('Revoked session')
        if not await self.client.set(self.key(ticket),json.dumps(claim),ex=20,nx=True):raise ValueError('Ticket collision')
        return ticket

    async def consume(self,ticket):
        if len(ticket)!=43 or any(c not in 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-' for c in ticket):return None
        value=await self.client.getdel(self.key(ticket))
        if value is None:return None
        claim=json.loads(value)
        if claim['expires_at']<=time.time() or await self.revoked(claim['session_key']):return None
        return claim

    async def revoked(self,key):
        return bool(await self.client.exists(self.prefix+'revoked:'+key))

    async def revoke(self,key,expires_at):
        await self.client.set(self.prefix+'revoked:'+key,'1',ex=max(1,int(expires_at-time.time())+1))

    async def close(self):
        await self.client.aclose()
