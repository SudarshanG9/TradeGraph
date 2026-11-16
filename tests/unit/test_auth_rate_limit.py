from types import SimpleNamespace
import pytest
import redis
from fastapi import HTTPException
from backend.auth.rate_limit import check_limit


def test_limits_are_shared_bounded_and_dependency_failures_are_classified(monkeypatch):
    seen=[]
    class Client:
        count=0
        def eval(self,script,n,key,window):
            seen.append(key); self.__class__.count+=1; return self.count
        def close(self):pass
    monkeypatch.setattr(redis.Redis,'from_url',lambda *a,**k:Client())
    settings=SimpleNamespace(postgres_db='isolated_test',redis_url='redis://private')
    check_limit(settings,'signup','private@example.test',1,60)
    with pytest.raises(HTTPException) as error:check_limit(settings,'signup','private@example.test',1,60)
    assert error.value.status_code==429 and seen[0]==seen[1]
    assert 'private@example.test' not in seen[0]
    def unavailable(*a,**k):raise redis.ConnectionError()
    monkeypatch.setattr(Client,'eval',unavailable)
    with pytest.raises(HTTPException) as error:check_limit(settings,'signup','private@example.test',1,60)
    assert error.value.status_code==503
