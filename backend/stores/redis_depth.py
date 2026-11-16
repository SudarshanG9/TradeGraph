"""Atomic price-sorted top-20 cache; quantities never pass through Lua floats."""
from datetime import datetime,timezone
import json
import redis

UPDATE = '''
local oldepoch=redis.call('HGET',KEYS[5],'epoch')
local oldversion=redis.call('HGET',KEYS[5],'version')
if oldepoch==ARGV[1] and oldversion and oldversion>=ARGV[2] then return 0 end
local book=cjson.decode(ARGV[4])
for side=1,2 do
 local wanted={}
 for _,level in ipairs(book[side]) do wanted[level[1]]=level[2] end
 for _,price in ipairs(redis.call('ZRANGE',KEYS[side],0,-1)) do
  if not wanted[price] then redis.call('ZREM',KEYS[side],price);redis.call('HDEL',KEYS[side+2],price) end
 end
 for _,level in ipairs(book[side]) do
  redis.call('ZADD',KEYS[side],level[1],level[1]);redis.call('HSET',KEYS[side+2],level[1],level[2])
 end
 if #book[side]==0 then redis.call('DEL',KEYS[side],KEYS[side+2]) end
end
redis.call('HSET',KEYS[5],'epoch',ARGV[1],'version',ARGV[2],'as_of',ARGV[3])
return 1
'''
READ = '''
local result={redis.call('HGETALL',KEYS[5]),{}, {}}
for side=1,2 do
 local prices
 if side==1 then prices=redis.call('ZREVRANGE',KEYS[side],0,19) else prices=redis.call('ZRANGE',KEYS[side],0,19) end
 for _,p in ipairs(prices) do table.insert(result[side+1],{p,redis.call('HGET',KEYS[side+2],p)}) end
end
return result
'''


class RedisDepth:
    def __init__(self,url,timeout=3):
        self.client=redis.Redis.from_url(url,decode_responses=True,socket_connect_timeout=timeout,socket_timeout=timeout)

    def keys(self,symbol):
        base=f'depth:{symbol}'
        return [base+':bids',base+':asks',base+':bids:qty',base+':asks:qty',base+':meta']

    def apply(self,symbol,bids,asks,*,version,epoch,as_of=None):
        sides=[]
        for levels,reverse in ((bids,True),(asks,False)):
            for price,qty in levels:
                if type(price) is not int or not 0<price<=2**53-1 or type(qty) is not int or qty<=0:
                    raise ValueError('Invalid exact cache price/quantity')
            sides.append([[str(p),str(q)] for p,q in sorted(levels,reverse=reverse)[:20]])
        stamp=as_of or datetime.now(timezone.utc).isoformat().replace('+00:00','Z')
        return bool(self.client.eval(UPDATE,5,*self.keys(symbol),epoch,f'{version:020d}',stamp,json.dumps(sides)))

    def read(self,symbol,max_age=30):
        metadata,bids,asks=self.client.eval(READ,5,*self.keys(symbol))
        metadata=dict(zip(metadata[::2],metadata[1::2]))
        stamp=metadata.get('as_of')
        stale=not stamp or (datetime.now(timezone.utc)-datetime.fromisoformat(stamp)).total_seconds()>max_age
        return {'symbol':symbol,'bids':[{'price_ticks':int(p),'quantity':int(q)} for p,q in bids],
                'asks':[{'price_ticks':int(p),'quantity':int(q)} for p,q in asks],
                'epoch':metadata.get('epoch'),'as_of':stamp,'stale':bool(stale),'version':int(metadata.get('version',0))}

    def close(self):
        self.client.close()
