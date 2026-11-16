"""Shared fixed-window abuse limits; keys contain hashes, never credentials."""
import hashlib
import redis
from fastapi import HTTPException

SCRIPT = """local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return n"""


def check_limit(settings, category, identity, limit, window):
    key='tradegraph:auth:'+hashlib.sha256((settings.postgres_db+':'+category+':'+identity).encode()).hexdigest()
    client=redis.Redis.from_url(settings.redis_url,socket_connect_timeout=2,socket_timeout=2)
    try:
        if client.eval(SCRIPT,1,key,window)>limit:
            raise HTTPException(429,detail='RATE_LIMITED',headers={'Retry-After':str(window)})
    except redis.RedisError:
        raise HTTPException(503,detail='AUTH_SERVICE_UNAVAILABLE') from None
    finally:client.close()
