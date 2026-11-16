"""Canonical committed identities; delivery never calls financial settlement."""
from backend.events.trade_event import TradeEvent


def execution_event(row):
    return TradeEvent(row['id'], row['instrument_id'], row['buy_order_id'], row['sell_order_id'],
                      row['buy_trader_id'], row['sell_trader_id'], row['price_ticks'], row['quantity'],
                      max(row['buy_order_id'], row['sell_order_id']), row['executed_at'])


def process_one(database, consumer, handler):
    if consumer not in ('graph', 'regime'):
        raise ValueError('Unknown durable consumer')
    with database.connect() as conn:
        # Serialize writers of each derived projection, including read-before-write.
        # This also prevents an old aggregate from overwriting a newer replay.
        held = conn.execute('SELECT pg_try_advisory_xact_lock(hashtext(%s)) AS held',
                            ('tradegraph-outbox-'+consumer,)).fetchone()['held']
        if not held:
            return False
        row = conn.execute('''SELECT execution_id,payload,attempts FROM public.event_outbox
            WHERE consumer=%s AND completed_at IS NULL AND next_attempt_at<=clock_timestamp()
              AND (%s<>'regime' OR payload IS NOT NULL)
            ORDER BY execution_id LIMIT 1 FOR UPDATE SKIP LOCKED''', (consumer, consumer)).fetchone()
        if row is None:
            return False
        event_row = conn.execute('SELECT * FROM public.execution WHERE id=%s', (row['execution_id'],)).fetchone()
        try:
            handler(execution_event(event_row), row['payload'])
        except Exception as exc:
            # Only the exception class is retained, never credentials or payloads.
            conn.execute('''UPDATE public.event_outbox SET attempts=attempts+1,last_error=%s,
                next_attempt_at=clock_timestamp()+(%s * interval '1 second')
                WHERE execution_id=%s AND consumer=%s''',
                (type(exc).__name__[:120], min(60, 2**min(row['attempts'], 6)), row['execution_id'], consumer))
        else:
            conn.execute('''UPDATE public.event_outbox SET completed_at=clock_timestamp(),
                attempts=attempts+1,last_error=NULL WHERE execution_id=%s AND consumer=%s''',
                (row['execution_id'], consumer))
    return True
