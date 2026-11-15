"""Measured distributions, never a microsecond performance pass/fail target."""
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
from time import perf_counter_ns
from decimal import Decimal,localcontext
from backend.matching.order_book import OrderBook,Order
from backend.matching.fenwick import FenwickTree
from backend.matching.rolling_vwap import RollingVWAP

WARMUP=200
SAMPLES=5000


def distribution(samples,scale=1000):
    ordered=sorted(x/scale for x in samples)
    return {'samples':len(ordered),'median':statistics.median(ordered),
            'p95':ordered[math.ceil(len(ordered)*.95)-1],
            'p99':ordered[math.ceil(len(ordered)*.99)-1]}


def measure(items,operation,warmup=WARMUP):
    for item in items[:warmup]: operation(item)
    elapsed=[]
    for item in items[warmup:]:
        start=perf_counter_ns();operation(item);elapsed.append(perf_counter_ns()-start)
    return distribution(elapsed)


def test_isolated_matching_algorithms_and_reference_scan_benchmarks():
    metrics={};total=SAMPLES+WARMUP
    orders=[Order(i+1,'a',1,'BUY',100,1) for i in range(total)]
    book=OrderBook();metrics['submit_existing_level_us']=measure(orders,book.submit)
    assert book.depth(1,'BUY')==[(100,total)]
    new=OrderBook()
    metrics['submit_new_level_us']=measure([Order(i+1,'a',1,'BUY',100+i,1) for i in range(total)],new.submit)
    cancel=OrderBook()
    for item in orders: cancel.submit(item)
    metrics['known_node_cancel_us']=measure(list(range(1,total+1)),cancel.cancel)
    assert cancel.depth(1,'BUY')==[]
    match=OrderBook()
    for i in range(total): match.submit(Order(i+1,'a',1,'SELL',100,1))
    metrics['one_fill_match_us']=measure([Order(total+i+1,'b',1,'BUY',100,1) for i in range(total)],match.submit)
    assert match.depth(1,'SELL')==[]
    depth=OrderBook()
    for i in range(1024): depth.submit(Order(i+1,'a',1,'BUY',100+i,1))
    metrics['depth_1024_levels_us']=measure(list(range(2200)),lambda _:depth.depth(1,'BUY'))

    size=65536;expected=[i%100+1 for i in range(size)];bit=FenwickTree(size)
    for i,q in enumerate(expected): bit.point_add(i,q)
    updates=list(range(total))
    metrics['fenwick_point_add_us']=measure(updates,lambda i:bit.point_add(i,1))
    for i in updates: expected[i]+=1
    assert bit.prefix_sum(size-1)==sum(expected)
    lo,hi=2048,64000;answer=sum(expected[lo:hi+1])
    assert bit.range_sum(lo,hi)==answer
    items=list(range(2200))
    metrics['fenwick_range_65536_us']=measure(items,lambda _:bit.range_sum(lo,hi))
    metrics['direct_scan_range_65536_us']=measure(items,lambda _:sum(expected[lo:hi+1]))

    window=4096;history=[(100+i%53,1+i%10) for i in range(total)]
    ring=RollingVWAP(window)
    metrics['prefix_ring_add_us']=measure(history,lambda pq:ring.add(*pq))
    reference=history[-window:]
    numerator=sum(p*q for p,q in reference);denominator=sum(q for _,q in reference)
    assert ring.sums()==(numerator,denominator)
    def scan(_):
        with localcontext() as context:
            context.prec=50
            return Decimal(sum(p*q for p,q in reference))/Decimal(sum(q for _,q in reference))
    assert ring.value()==scan(None)
    metrics['prefix_ring_vwap_4096_us']=measure(items,lambda _:ring.value())
    metrics['rescan_vwap_4096_us']=measure(items,scan)
    assert all(v['samples']>=2000 and v['p95']>0 for v in metrics.values())
    try: cpu=subprocess.check_output(['/usr/sbin/sysctl','-n','machdep.cpu.brand_string'],text=True).strip()
    except (OSError,subprocess.CalledProcessError): cpu=platform.processor()
    result={'python':sys.version,'platform':platform.platform(),'cpu':cpu,'logical_cpus':os.cpu_count(),
            'warmup_per_operation':WARMUP,'units':'microseconds','metrics':metrics,
            'notes':'Prebuilt orders; timer wraps the actual function call. No DB/network in measured matching operations. Coordinate-expansion rebuild is not a Fenwick steady-state operation.'}
    if os.environ.get('TRADEGRAPH_BENCHMARK_REPORT'):
        Path(os.environ['TRADEGRAPH_BENCHMARK_REPORT']).write_text(json.dumps(result,indent=2))
