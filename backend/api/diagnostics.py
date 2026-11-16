"""Bounded request diagnostics: no bodies, credentials, URL queries or identities."""
import json
import logging
import re
import time
from uuid import uuid4
from starlette.middleware.base import BaseHTTPMiddleware
logger=logging.getLogger('tradegraph.requests')


class Diagnostics(BaseHTTPMiddleware):
    async def dispatch(self,request,call_next):
        supplied=request.headers.get('x-request-id','')
        correlation=supplied if re.fullmatch('[a-f0-9-]{36}',supplied) else str(uuid4())
        start=time.monotonic()
        status=500
        try:
            response=await call_next(request)
            status=response.status_code
            response.headers['X-Request-ID']=correlation
            response.headers['Cache-Control']='no-store'
            return response
        finally:
            route=request.scope.get('route')
            endpoint=getattr(route,'path','unmatched')
            logger.info(json.dumps({'request_id':correlation,'endpoint':endpoint,'status':status,'duration_ms':round((time.monotonic()-start)*1000,2),'dependency':'unavailable' if status in (502,503,504) else 'none'}))
