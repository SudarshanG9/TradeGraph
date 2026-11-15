from contextlib import asynccontextmanager
import asyncio
import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from pydantic import BaseModel
from typing import Literal
from backend.config import Settings
from backend.stores.postgres import Database
from backend.risk.order_reservation import Coordinator
from backend.api.routes import auth, orders, admin, market
from backend.workers.settlement_worker import SettlementWorker
from backend.workers.cache_worker import CacheWorker
from backend.stores.redis_depth import RedisDepth
from backend.stores.neo4j_graph import Neo4jGraph
from backend.workers.graph_worker import GraphWorker
from backend.stores.regimes import Regimes
from backend.workers.regime_worker import RegimeWorker


class HealthResponse(BaseModel):
    status: Literal['ok','unhealthy']
    dependencies: dict[str, Literal['up','down']]
    trading_ready: bool


def create_app(settings=None, *, settlement=True):
    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings or Settings.from_env()
        app.state.database = Database(app.state.settings)
        app.state.service = Coordinator(app.state.database, app.state.settings)
        try:
            if settlement:
                app.state.depth=RedisDepth(app.state.settings.redis_url,app.state.settings.health_timeout_seconds)
                cache=CacheWorker(app.state.database,app.state.depth,app.state.service.dispatcher)
                app.state.service.derived['redis']=cache
                app.state.service.book_observers.append(cache.publish)
                cache.start()
                for row in await asyncio.to_thread(app.state.database.query,'SELECT id FROM instrument'):
                    app.state.service.notify_book(row['id'])
                app.state.service.worker = SettlementWorker(app.state.database,app.state.service.engine,app.state.service.dispatcher)
                app.state.graph=Neo4jGraph(app.state.settings,app.state.database)
                graph=GraphWorker(app.state.graph,app.state.service.dispatcher)
                app.state.service.derived['neo4j']=graph
                graph.start()
                graph.publish(None)
                app.state.service.worker.after_commit.append(graph.publish)
                app.state.regimes=Regimes(app.state.database)
                regimes=RegimeWorker(app.state.regimes,app.state.service.dispatcher)
                app.state.service.derived['regimes']=regimes
                app.state.service.book_observers.append(regimes.record_book)
                regimes.start()
                app.state.service.worker.after_commit.append(regimes.publish_settled)
                app.state.service.worker.start()
            yield
        finally:
            if app.state.service.worker:
                await app.state.service.worker.stop()
            for consumer in app.state.service.derived.values():
                await consumer.stop()
            if hasattr(app.state,'depth'):
                app.state.depth.close()
            if hasattr(app.state,'graph'):
                app.state.graph.close()
            app.state.service.close()

    application = FastAPI(title='TradeGraph', version='1.0', lifespan=lifespan)
    application.include_router(auth.router)
    application.include_router(orders.router)
    application.include_router(admin.router)
    application.include_router(market.router)

    @application.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return JSONResponse({'error':{'code':str(exc.detail),'message':str(exc.detail)}}, status_code=exc.status_code)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        return JSONResponse({'error':{'code':'INVALID_REQUEST','message':'Request validation failed'}}, status_code=422)

    @application.exception_handler(psycopg.Error)
    async def database_error(request, exc):
        if exc.sqlstate == 'P0001':
            code, status = 'INSUFFICIENT_FUNDS', 409
        elif exc.sqlstate in ('22023','22003','23514','23503'):
            code, status = 'INVALID_ORDER', 422
        elif exc.sqlstate=='23505':
            code, status = 'EVENT_CONFLICT', 409
        else:
            code, status = 'DATABASE_UNAVAILABLE', 503
        return JSONResponse({'error':{'code':code,'message':code}}, status_code=status)

    @application.get('/health', response_model=HealthResponse)
    async def health():
        s = application.state.settings
        def probe(name):
            try:
                if name == 'postgres':
                    application.state.database.query('SELECT 1')
                elif name == 'redis':
                    import redis
                    client = redis.Redis.from_url(s.redis_url, socket_connect_timeout=s.health_timeout_seconds, socket_timeout=s.health_timeout_seconds)
                    try: client.ping()
                    finally: client.close()
                else:
                    from neo4j import GraphDatabase
                    with GraphDatabase.driver(s.neo4j_uri, auth=(s.neo4j_user,s.neo4j_password), connection_timeout=s.health_timeout_seconds) as driver:
                        driver.verify_connectivity()
                return 'up'
            except Exception:
                return 'down'
        names = ('postgres','redis','neo4j')
        dependencies = dict(zip(names, await asyncio.gather(*(asyncio.to_thread(probe,n) for n in names))))
        for name,consumer in application.state.service.derived.items():
            if name not in dependencies or consumer.failed:
                dependencies[name]='down' if consumer.failed else 'up'
        ready = not application.state.service.dispatcher.failure and dependencies['postgres']=='up'
        return {'status':'ok' if ready and all(v=='up' for v in dependencies.values()) else 'unhealthy','dependencies':dependencies,'trading_ready':ready}

    return application


app = create_app()
