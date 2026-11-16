"""Serialized book-snapshot CPU comparison, excluding reservation/network I/O."""
import json,subprocess,sys,time,types,statistics
from backend.matching.order_book import OrderBook,Order


def baseline():
    text=subprocess.run(['git','show','f019866:backend/matching/order_book.py'],capture_output=True,text=True,check=True).stdout
    module=types.ModuleType('orderbook_before');sys.modules[module.__name__]=module
    exec(compile(text,'orderbook_before','exec'),module.__dict__)
    return module.OrderBook


def measure(cls,instruments,levels):
    book=cls()
    for i in range(instruments):
        for j in range(levels):book.submit(Order(i*levels+j+1,'maker',i+1,'BUY',j+1,1))
    book.depth(1,'BUY')
    samples=[]
    for _ in range(1000):
        started=time.perf_counter_ns();snapshot=book.depth(1,'BUY');samples.append(time.perf_counter_ns()-started)
        assert len(snapshot)==levels
    return {'median_us':statistics.median(samples)/1000,'p95_us':sorted(samples)[949]/1000,'samples':len(samples)}


if __name__=='__main__':
    print(json.dumps({name:{'before':measure(baseline(),*shape),'after':measure(OrderBook,*shape)}
      for name,shape in {'many_instruments':(200,10),'many_levels':(1,2000)}.items()},indent=2))
