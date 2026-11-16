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
from backend.api.routes import auth, orders, admin, market, simulator, instruments
from backend.simulator.live_supervisor import LiveMarketSupervisor
from backend.workers.settlement_worker import SettlementWorker
from backend.workers.cache_worker import CacheWorker
from backend.stores.redis_depth import RedisDepth
from backend.stores.neo4j_graph import Neo4jGraph
from backend.workers.graph_worker import GraphWorker
from backend.stores.regimes import Regimes
from backend.workers.regime_worker import RegimeWorker
from backend.events.trade_event import TradeEvent
from backend.events.live_bus import LiveBus
from backend.api import websocket
from backend.api.diagnostics import Diagnostics
from backend.auth.websocket_ticket import TicketStore
from backend.workers.housekeeping_worker import HousekeepingWorker
from backend.workers.outbox_worker import OutboxWorker


class Readiness(BaseModel):
    matching_owner: bool
    replay_complete: bool
    replayed_executions: int
    financial_settlement: bool
    derived_ready: bool
    reconciliation_required: bool
    closing: bool


class HealthResponse(BaseModel):
    status: Literal['ok','unhealthy']
    dependencies: dict[str, Literal['up','down']]
    trading_ready: bool
    readiness: Readiness


def create_app(settings=None, *, settlement=True):
    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings or Settings.from_env()
        app.state.database = Database(app.state.settings)
        app.state.service = Coordinator(app.state.database, app.state.settings)
        app.state.live_socket_tasks=set()
        app.state.live_tickets=TicketStore(app.state.settings.redis_url,app.state.settings.postgres_db)
        app.state.live_bus = LiveBus(app.state.service.epoch)
        app.state.service.live_bus = app.state.live_bus
        app.state.live_simulator = LiveMarketSupervisor(app.state.service, app.state.database)
        app.state.outbox_workers = []
        try:
            # Only settled history is rehydrated. Active orders already triggered
            # a fail-closed reconciliation stop in acquire_owner().
            app.state.replay_complete = False
            app.state.replayed_executions = 0
            batches = app.state.database.execution_batches()
            try:
                while (batch := await app.state.service.committed_io(next, batches, None)) is not None:
                    for row in batch:
                        app.state.service.engine.apply_settled(TradeEvent(row['id'],row['instrument_id'],row['buy_order_id'],row['sell_order_id'],
                            row['buy_trader_id'],row['sell_trader_id'],row['price_ticks'],row['quantity'],max(row['buy_order_id'],row['sell_order_id']),row['executed_at']))
                        app.state.replayed_executions += 1
            finally:
                await asyncio.to_thread(batches.close)
            app.state.replay_complete = True
            if settlement:
                app.state.depth=RedisDepth(app.state.settings.redis_url,app.state.settings.health_timeout_seconds)
                cache=CacheWorker(app.state.database,app.state.depth,app.state.service.dispatcher)
                loop=asyncio.get_running_loop()
                cache.after_apply=lambda snapshot:loop.call_soon_threadsafe(app.state.live_bus.book_changed,snapshot)
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
                app.state.regimes=Regimes(app.state.database)
                regimes=RegimeWorker(app.state.regimes,app.state.service.dispatcher)
                app.state.service.derived['regimes']=regimes
                app.state.service.book_observers.append(regimes.record_book)
                # Keep the owner-loop observation recorder, but durable consumers
                # replace volatile graph/regime publication queues.
                app.state.database.regime_books = regimes.books
                for row in await asyncio.to_thread(app.state.database.query,'SELECT id FROM instrument'):
                    regimes.record_book(app.state.service.book_snapshot(row['id']))
                for name,handler in (('graph',lambda event,payload:app.state.graph.apply(event)),
                                     ('regime',app.state.regimes.apply_observation)):
                    durable=OutboxWorker(app.state.database,name,handler)
                    app.state.outbox_workers.append(durable)
                    durable.start()
                app.state.service.worker.after_commit.append(app.state.live_bus.settled)
                app.state.service.worker.start()
            app.state.housekeeping = HousekeepingWorker(app.state.database, app.state.settings)
            if app.state.settings.maintenance_enabled:
                app.state.housekeeping.start()
            yield
        finally:
            for task in app.state.live_socket_tasks: task.cancel()
            await asyncio.gather(*app.state.live_socket_tasks,return_exceptions=True)
            await app.state.live_tickets.close()
            if hasattr(app.state, 'housekeeping'):
                await app.state.housekeeping.stop()
            await app.state.live_simulator.shutdown()
            await app.state.service.finish_admissions()
            if app.state.service.worker:
                await app.state.service.worker.stop()
            for consumer in app.state.outbox_workers:
                await consumer.stop()
            for consumer in app.state.service.derived.values():
                await consumer.stop()
            if hasattr(app.state,'depth'):
                app.state.depth.close()
            if hasattr(app.state,'graph'):
                app.state.graph.close()
            app.state.service.close()

    application = FastAPI(title='TradeGraph', version='1.0', lifespan=lifespan)
    application.add_middleware(Diagnostics)
    application.include_router(websocket.router)
    application.include_router(auth.router)
    application.include_router(orders.router)
    application.include_router(admin.router)
    application.include_router(market.router)
    application.include_router(simulator.router)
    application.include_router(instruments.router)

    @application.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return JSONResponse({'error':{'code':str(exc.detail),'message':str(exc.detail)}}, status_code=exc.status_code,headers=exc.headers)

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
            unavailable=consumer.failed or (name=='neo4j' and not consumer.ready)
            if name not in dependencies or unavailable:
                dependencies[name]='down' if unavailable else 'up'
        service = application.state.service
        try:
            owner_held = bool(await asyncio.to_thread(service.verify_owner))
        except Exception:
            owner_held = False
        worker = service.worker
        financial = bool(worker and worker.task and not worker.task.done() and not service.dispatcher.failure)
        replay_complete = application.state.replay_complete
        derived_ready = all(value == 'up' for name,value in dependencies.items() if name != 'postgres')
        ready = bool(owner_held and replay_complete and financial and not service.closing and dependencies['postgres']=='up')
        return {'status':'ok' if ready and all(v=='up' for v in dependencies.values()) else 'unhealthy',
                'dependencies':dependencies,'trading_ready':ready,
                'readiness':{'matching_owner':owner_held,'replay_complete':replay_complete,
                'replayed_executions':application.state.replayed_executions,'financial_settlement':financial,
                'derived_ready':derived_ready,'reconciliation_required':bool(service.dispatcher.failure or not owner_held),
                'closing':service.closing}}


    return application


app = create_app()
