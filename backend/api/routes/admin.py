import asyncio
from datetime import datetime
from uuid import UUID
from typing import Literal
from pydantic import BaseModel,Field
from fastapi import APIRouter,Depends,Request,Query,HTTPException
from backend.api.dependencies import admin

router=APIRouter(prefix='/admin',dependencies=[Depends(admin)])


class Cycle(BaseModel):
    trader_ids: list[UUID]
    edge_counts: list[int]


class Cycles(BaseModel):
    candidates: list[Cycle]


class RegimeMatch(BaseModel):
    id: int
    instrument_id: int
    captured_at: datetime
    features: list[float]=Field(min_length=6,max_length=6)
    cosine_distance: float


class Similar(BaseModel):
    matches: list[RegimeMatch]


class Disclosure(BaseModel):
    id: int
    instrument_id: int | None
    title: str
    published_at: datetime
    rank: float


class Search(BaseModel):
    items: list[Disclosure]


class Desk(BaseModel):
    desk_id: int
    realized_pnl: int
    execution_volume: int


class Rollup(BaseModel):
    items: list[Desk]


class Optimizer(BaseModel):
    scenario: Literal['price_band','recent_executions']
    row_count: int
    dataset_size: int
    plans: dict[str,dict]


@router.get('/regimes/similar',response_model=Similar)
async def similar(request: Request,instrument_id: int=Query(...,gt=0,le=2**31-1),
                  features: list[float] | None=Query(None),current: bool=False,k: int=Query(10,ge=1,le=100)):
    if not hasattr(request.app.state,'regimes'):
        raise HTTPException(503,detail='REGIMES_UNAVAILABLE')
    if (features is not None)==current:
        raise HTTPException(422,detail='CHOOSE_FEATURES_OR_CURRENT')
    store=request.app.state.regimes
    try:
        if current:
            row=await asyncio.to_thread(store.capture,instrument_id,request.app.state.service.book_snapshot(instrument_id))
            if row is None: raise HTTPException(404,detail='NO_MARKET_OBSERVATIONS')
            features=row['features']
        return {'matches':await asyncio.to_thread(store.similar,features,instrument_id,k)}
    except ValueError:
        raise HTTPException(422,detail='INVALID_VECTOR') from None


@router.get('/disclosures/search',response_model=Search)
async def disclosures(request: Request,q: str=Query(...,min_length=1,max_length=500),limit: int=Query(20,ge=1,le=100)):
    from backend.stores.regimes import Regimes
    return {'items':await asyncio.to_thread(Regimes(request.app.state.database).search,q,limit)}


@router.get('/surveillance/cycles',response_model=Cycles)
async def cycles(request: Request,limit: int=Query(25,ge=1,le=100)):
    if not hasattr(request.app.state,'graph'):
        raise HTTPException(503,detail='GRAPH_UNAVAILABLE')
    if request.app.state.service.derived['neo4j'].failed or not request.app.state.service.derived['neo4j'].ready:
        raise HTTPException(503,detail='GRAPH_UNAVAILABLE')
    try:
        return {'candidates':await asyncio.to_thread(request.app.state.graph.cycles,limit)}
    except Exception:
        raise HTTPException(503,detail='GRAPH_UNAVAILABLE') from None


@router.get('/desks/rollup',response_model=Rollup)
async def rollup(request: Request):
    return {'items':await asyncio.to_thread(request.app.state.database.named,'rollup')}


@router.get('/optimizer/compare',response_model=Optimizer)
async def optimizer(request: Request, scenario: Literal['price_band','recent_executions']='price_band',
                    instrument_id: int=Query(1,gt=0), lower_ticks: int=Query(1,gt=0),upper_ticks: int=Query(2**53-1,gt=0)):
    return await asyncio.to_thread(request.app.state.database.optimizer,scenario,instrument_id,lower_ticks,upper_ticks)
