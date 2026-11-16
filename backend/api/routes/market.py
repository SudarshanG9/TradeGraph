import asyncio
import redis
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel
from fastapi import APIRouter,Depends,Request,HTTPException,Query
from backend.api.dependencies import actor

router=APIRouter(prefix='/market',dependencies=[Depends(actor)])


class Level(BaseModel):
    price_ticks: int
    quantity: int


class Book(BaseModel):
    epoch: str | None
    symbol: str
    bids: list[Level]
    asks: list[Level]
    as_of: datetime | None
    stale: bool
    version: int


class Trade(BaseModel):
    id: int
    instrument_id: int
    buy_order_id: int
    sell_order_id: int
    buy_trader_id: UUID
    sell_trader_id: UUID
    price_ticks: int
    quantity: int
    executed_at: datetime


class Trades(BaseModel):
    items: list[Trade]
    next_before_id: int | None


class Analytics(BaseModel):
    vwap_ticks: str | None
    window_fills: int
    band_volume: int
    as_of: datetime | None


async def instrument(request,symbol):
    rows=await asyncio.to_thread(request.app.state.database.query,'SELECT id,symbol FROM instrument WHERE symbol=%s',(symbol,))
    if not rows: raise HTTPException(404,detail='INSTRUMENT_NOT_FOUND')
    return rows[0]


@router.get('/{symbol}/book',response_model=Book)
async def book(symbol: str,request: Request):
    await instrument(request,symbol)
    if not hasattr(request.app.state,'depth'):
        raise HTTPException(503,detail='CACHE_UNAVAILABLE')
    try:
        snapshot=await asyncio.to_thread(request.app.state.depth.read,symbol)
        if snapshot['epoch']!=request.app.state.service.epoch:
            raise HTTPException(503,detail='DEPTH_RESYNC_REQUIRED')
        return snapshot
    except (redis.RedisError,ValueError,TypeError):
        raise HTTPException(503,detail='CACHE_UNAVAILABLE') from None


@router.get('/{symbol}/trades',response_model=Trades)
async def trades(symbol: str,request: Request,limit: int=Query(50,ge=1,le=100),before_id: int=Query(2**63-1,gt=0)):
    row=await instrument(request,symbol)
    rows=await asyncio.to_thread(request.app.state.database.query,
        'SELECT * FROM execution WHERE instrument_id=%s AND id<%s ORDER BY id DESC LIMIT %s',(row['id'],before_id,limit))
    return {'items':rows,'next_before_id':rows[-1]['id'] if len(rows)==limit else None}


@router.get('/{symbol}/analytics',response_model=Analytics)
async def analytics(symbol: str,request: Request,lower_ticks: int=Query(1,ge=0),upper_ticks: int=Query(2**53-1,ge=0)):
    row=await instrument(request,symbol)
    engine=request.app.state.service.engine
    value=engine.vwap[row['id']].value()
    return {'vwap_ticks':str(value) if value is not None else None,
            'window_fills':min(engine.window,engine.vwap[row['id']].count),
            'band_volume':engine.volume[row['id']].range_sum(lower_ticks,upper_ticks),
            'as_of':engine.latest_time.get(row['id'])}
