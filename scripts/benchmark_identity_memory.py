"""Repeatable synthetic retained-identity memory profile, not total engine RSS."""
from dataclasses import replace
from datetime import datetime,timezone
import gc,json,tracemalloc
from uuid import UUID
from backend.events.trade_event import TradeEvent
from backend.matching.engine import Engine


def measure(compact,count=10000,independent=False):
    base=TradeEvent(1,1,1,2,UUID(int=1),UUID(int=2),100,1,2,datetime(2026,1,1,tzinfo=timezone.utc))
    gc.collect();tracemalloc.start()
    records={}
    for i in range(1,count+1):
        event=(TradeEvent(i,1,int('10001'),int('10002'),UUID(str(base.buy_trader_id)),UUID(str(base.sell_trader_id)),
                          int('10000'),int('1000'),int('10002'),datetime.fromisoformat(base.occurred_at.isoformat()))
               if independent else replace(base,event_id=i))
        records[i]=Engine.event_identity(event) if compact else event
    current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    return dict(entries=len(records),retained_bytes=current,peak_bytes=peak)


if __name__=='__main__':
    print(json.dumps({'shared_references':{'full_events':measure(False),'packed':measure(True)},
      'independent_row_objects':{'full_events':measure(False,independent=True),'packed':measure(True,independent=True)},
      'limitation':'Retained synthetic map only, not total engine RSS; both remain O(history). Shared-reference events can use less memory than packed bytes.'},indent=2))
