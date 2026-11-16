"""Event-loop-only nonblocking fanout. Bounded queues cannot stop settlement."""
import asyncio
from dataclasses import dataclass, field
from backend.events.live_protocol import envelope


@dataclass(eq=False)
class Connection:
    identity: dict
    queue: asyncio.Queue=field(default_factory=lambda:asyncio.Queue(128))
    instruments: set=field(default_factory=set)
    sequence: int=0
    overflow: bool=False


class LiveBus:
    def __init__(self,epoch,max_connections=1024,max_per_user=4):
        self.epoch=epoch
        self.clients=set()
        self.max_connections=max_connections
        self.max_per_user=max_per_user
        self.dropped=0

    def connect(self,identity):
        if len(self.clients)>=self.max_connections or sum(c.identity['id']==identity['id'] for c in self.clients)>=self.max_per_user:
            raise ValueError('LIVE_CONNECTION_LIMIT')
        client=Connection(identity)
        self.clients.add(client)
        self.send(client,'resync.required')
        return client

    def disconnect(self,client):
        self.clients.discard(client)

    def send(self,client,kind,**fields):
        if client.overflow:return
        client.sequence+=1
        try:client.queue.put_nowait(envelope(kind,self.epoch,client.sequence,**fields))
        except asyncio.QueueFull:
            client.overflow=True
            self.dropped+=1

    def publish(self,kind,*,trader_ids=None,admin=False,**fields):
        # This method intentionally never awaits, reads a database or raises to
        # the financial caller. Losing notifications requires HTTP resync.
        try:
            for client in tuple(self.clients):
                if admin and client.identity['role']!='COMPLIANCE_ADMIN':continue
                if trader_ids is not None and str(client.identity.get('trader_id')) not in {str(t) for t in trader_ids}:continue
                if trader_ids is None and not admin and fields.get('instrument_id') not in client.instruments:continue
                self.send(client,kind,**fields)
        except Exception:
            self.dropped+=1
            for client in self.clients:client.overflow=True

    def book_changed(self,snapshot):
        self.publish('book.changed',instrument_id=snapshot['instrument_id'],version=snapshot['version'])

    def settled(self,event):
        self.publish('trade.committed',instrument_id=event.instrument_id,execution_id=str(event.event_id))
        self.publish('order.changed',trader_ids=(event.buy_trader_id,event.sell_trader_id),instrument_id=event.instrument_id)
        self.publish('account.changed',trader_ids=(event.buy_trader_id,event.sell_trader_id))
