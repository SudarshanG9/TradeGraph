"""Compare exact new-coordinate insertion CPU and retained allocation size."""
import gc,json,random,time,tracemalloc,subprocess,types
from backend.matching.fenwick import PriceVolumeIndex


def measure(cls,prices):
    gc.collect();tracemalloc.start();index=cls();samples=[]
    for p in prices:
        started=time.perf_counter_ns();index.add(p,1);samples.append(time.perf_counter_ns()-started)
    retained,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    assert index.range_sum(0,2**63-1)==len(prices)
    return dict(total_ms=sum(samples)/1e6,median_us=sorted(samples)[len(samples)//2]/1000,
                retained_bytes=retained,peak_bytes=peak,coordinates=len(prices))


def load_baseline():
    source=subprocess.run(['git','show','f53ab3b:backend/matching/fenwick.py'],check=True,capture_output=True,text=True).stdout
    module=types.ModuleType('fenwick_before');exec(compile(source,'fenwick_before','exec'),module.__dict__)
    return module.PriceVolumeIndex


if __name__=='__main__':
    baseline=load_baseline()
    rng=random.Random(20261116)
    cases={'clustered':list(range(1,2001)),'sparse_bigint':[rng.randrange(1,2**63) for _ in range(2000)]}
    print(json.dumps({name:{'before':measure(baseline,prices),'after':measure(PriceVolumeIndex,prices)} for name,prices in cases.items()},indent=2))
