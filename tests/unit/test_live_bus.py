from backend.events.live_bus import LiveBus


def identity(id,role='TRADER'):
    return {'id':id,'trader_id':id,'role':role}


def test_private_events_subscriptions_and_contiguous_per_connection_sequence():
    bus=LiveBus('owner')
    a,b,admin=(bus.connect(identity(x,role)) for x,role in [('a','TRADER'),('b','TRADER'),('admin','COMPLIANCE_ADMIN')])
    a.instruments.add(1);b.instruments.add(2)
    for c in (a,b,admin):assert c.queue.get_nowait()['type']=='resync.required'
    bus.publish('account.changed',trader_ids=['a'])
    bus.publish('book.changed',instrument_id=1,version=5)
    bus.publish('simulator.changed',admin=True)
    events=[a.queue.get_nowait(),a.queue.get_nowait()]
    assert [e['sequence'] for e in events]==[2,3]
    assert b.queue.empty() and admin.queue.get_nowait()['type']=='simulator.changed'
    assert all('trader_id' not in e for e in events)


def test_slow_clients_are_bounded_and_cannot_block_financial_publication():
    bus=LiveBus('owner',max_per_user=1)
    a=bus.connect(identity('a'))
    a.instruments.add(1)
    for _ in range(1000):bus.publish('book.changed',instrument_id=1,version=1)
    assert a.queue.qsize()==128 and a.overflow and bus.dropped==1
    import pytest
    with pytest.raises(ValueError):bus.connect(identity('a'))
    bus.disconnect(a)
    assert not bus.clients
