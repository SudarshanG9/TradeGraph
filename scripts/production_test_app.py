"""Test-only observability/fault injection; refuses non-test database configuration."""
from collections import deque
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import time
from backend.api.main import create_app as real_app
from backend.config import Settings


def create_app():
    settings=Settings.from_env()
    if not settings.postgres_db.startswith('tradegraph_test_'):
        raise ValueError('Test instrumentation requires isolated database')
    root=Path(os.environ['TRADEGRAPH_TEST_ROOT']).resolve()
    if not root.is_dir() or root.stat().st_mode & 0o077:
        raise ValueError('Private test artifact directory required')
    app=real_app(settings)
    original_lifespan=app.router.lifespan_context
    settlements=deque(maxlen=2048)
    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            database=application.state.database
            original=database.settle
            def measured(event):
                start=time.perf_counter()
                try:return original(event)
                finally:settlements.append((time.perf_counter()-start)*1000)
            database.settle=measured
            graph_apply=application.state.graph.apply
            def injected(event):
                if (root/'neo4j-unavailable').exists():
                    raise ConnectionError('Scoped test graph interruption')
                return graph_apply(event)
            application.state.graph.apply=injected
            yield
    app.router.lifespan_context=lifespan
    @app.get('/__test/metrics')
    async def metrics():
        state=app.state
        return {'clients':len(state.live_bus.clients),'socket_tasks':len(state.live_socket_tasks),
                'dropped':state.live_bus.dropped,
                'max_client_queue':max((c.queue.qsize() for c in state.live_bus.clients),default=0),
                'settlement_queue':state.service.dispatcher.queue.qsize(),
                'settlement_ms':list(settlements),'financial_failure':bool(state.service.dispatcher.failure),
                'cache_failed':bool(state.service.derived['redis'].failed),
                'database_connections':state.database.query("SELECT count(*) AS n FROM pg_stat_activity WHERE datname=current_database()")[0]['n']}
    class Observed:
        async def __call__(self,scope,receive,send):
            if scope['type']=='websocket':
                names={key.lower() for key,_ in scope['headers']}
                with (root/'upstream-headers.jsonl').open('a') as stream:
                    stream.write(json.dumps({'cookie':b'cookie' in names,'authorization':b'authorization' in names,
                                             'ticket_offered':any(p.startswith('ticket.') for p in scope.get('subprotocols',[]))})+'\n')
            await app(scope,receive,send)
    return Observed()
