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
from backend.api.routes import auth, orders, admin
from backend.workers.settlement_worker import SettlementWorker


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
        if settlement:
            app.state.service.worker = SettlementWorker(app.state.database,app.state.service.engine,app.state.service.dispatcher)
            app.state.service.worker.start()
        try:
            yield
        finally:
            if app.state.service.worker:
                await app.state.service.worker.stop()
            app.state.service.close()

    application = FastAPI(title='TradeGraph', version='1.0', lifespan=lifespan)
    application.include_router(auth.router)
    application.include_router(orders.router)
    application.include_router(admin.router)

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
        ready = not application.state.service.dispatcher.failure and all(v=='up' for v in dependencies.values())
        return {'status':'ok' if ready else 'unhealthy','dependencies':dependencies,'trading_ready':ready}

    return application


app = create_app()
