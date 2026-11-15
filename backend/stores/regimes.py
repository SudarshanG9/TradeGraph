"""Engineered six-dimensional observations, retained in the existing VECTOR(6)."""
from datetime import datetime,timedelta,timezone
from fractions import Fraction
import json
import math
import statistics
from threading import Lock


def validate_vector(values):
    if not isinstance(values,(list,tuple)) or len(values)!=6:
        raise ValueError('Exactly six finite features required')
    try:
        result=[float(x) for x in values if type(x) in (int,float)]
    except (OverflowError,ValueError):
        raise ValueError('Exactly six finite features required') from None
    if len(result)!=6 or not all(math.isfinite(x) for x in result) or not any(result):
        raise ValueError('Finite nonzero six-vector required')
    return result


def market_features(bids,asks,recent,history):
    """All ratios are nonfinancial features; money remains integer elsewhere."""
    if not bids and not asks and not recent and not history:
        return None
    bid_qty=sum(q for _,q in bids); ask_qty=sum(q for _,q in asks)
    total=bid_qty+ask_qty
    spread=max(asks[0][0]-bids[0][0],0) if bids and asks else 0
    imbalance=(bid_qty-ask_qty)/total if total else 0
    volume=sum(r['quantity'] for r in history)
    vwap=Fraction(sum(r['price_ticks']*r['quantity'] for r in history),volume) if volume else None
    drift=float((history[-1]['price_ticks']-vwap)/max(vwap,1)) if vwap is not None else 0
    returns=[(b['price_ticks']-a['price_ticks'])/a['price_ticks'] for a,b in zip(recent,recent[1:])]
    volatility=statistics.pstdev(returns) if returns else 0
    clamp=lambda x,low=0,high=1:max(low,min(high,float(x)))
    return [clamp(spread/100),clamp(imbalance,-1,1),clamp(drift,-1,1),
            clamp(len(recent)/100),clamp(bid_qty/total if total else 0.5),clamp(volatility)]


class Regimes:
    def __init__(self,database):
        self.database=database
        self.capture_locks={}
        self.versions={}

    def upsert(self,instrument,captured_at,features):
        features=validate_vector(features)
        with self.database.admin_context() as conn:
            return conn.execute("""INSERT INTO regime_snapshot(instrument_id,captured_at,features) VALUES (%s,%s,%s::vector)
              ON CONFLICT(instrument_id,captured_at) DO UPDATE SET features=EXCLUDED.features RETURNING id""",
              (instrument,captured_at,json.dumps(features,allow_nan=False))).fetchone()['id']

    def capture(self,instrument,snapshot,as_of=None):
        with self.capture_locks.setdefault(instrument,Lock()):
            version=(snapshot.get('epoch'),snapshot.get('version',0))
            previous=self.versions.get(instrument)
            if previous and previous[0]==version[0] and previous[1]>version[1]:
                with self.database.admin_context() as conn:
                    row=conn.execute('SELECT id,instrument_id,captured_at,features::text AS features FROM regime_snapshot WHERE instrument_id=%s ORDER BY captured_at DESC LIMIT 1',(instrument,)).fetchone()
                if row: row['features']=json.loads(row['features'])
                return row
            result=self._capture(instrument,snapshot,as_of)
            if result is not None: self.versions[instrument]=version
            return result

    def _capture(self,instrument,snapshot,as_of=None):
        now=as_of or datetime.now(timezone.utc)
        recent=self.database.query('SELECT price_ticks,quantity,executed_at FROM execution WHERE instrument_id=%s AND executed_at BETWEEN %s AND %s ORDER BY executed_at,id',(instrument,now-timedelta(seconds=60),now))
        history=list(reversed(self.database.query('SELECT price_ticks,quantity FROM execution WHERE instrument_id=%s ORDER BY id DESC LIMIT 100',(instrument,))))
        vector=market_features(snapshot.get('bids',[]),snapshot.get('asks',[]),recent,history)
        if vector is None: return None
        captured=now.replace(second=0,microsecond=0)
        return {'id':self.upsert(instrument,captured,vector),'instrument_id':instrument,'captured_at':captured,'features':vector}

    def similar(self,features,instrument=None,limit=10):
        rows=self.database.named('similar',{'features':json.dumps(validate_vector(features),allow_nan=False),'instrument_id':instrument,'limit':limit})
        for row in rows: row['features']=json.loads(row['features'])
        return rows

    def prune(self,cutoff,instrument):
        # Explicit instrument scope; never erase unrelated user snapshots.
        with self.database.admin_context() as conn:
            return len(conn.execute('DELETE FROM regime_snapshot WHERE captured_at<%s AND instrument_id=%s RETURNING id',(cutoff,instrument)).fetchall())

    def disclosure(self,instrument,title,body):
        with self.database.admin_context() as conn:
            return conn.execute('INSERT INTO market_disclosure(instrument_id,title,body) VALUES (%s,%s,%s) RETURNING id',(instrument,title,body)).fetchone()['id']

    def search(self,text,limit=20):
        return self.database.named('fts',{'q':text,'limit':limit})
