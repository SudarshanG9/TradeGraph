import asyncio
import redis
from fastapi import APIRouter,Depends,Request,HTTPException,Query
from backend.api.dependencies import actor

router=APIRouter(prefix='/market',dependencies=[Depends(actor)])


async def instrument(request,symbol):
    rows=await asyncio.to_thread(request.app.state.database.query,'SELECT id,symbol FROM instrument WHERE symbol=%s',(symbol,))
    if not rows: raise HTTPException(404,detail='INSTRUMENT_NOT_FOUND')
    return rows[0]


@router.get('/{symbol}/book')
async def book(symbol: str,request: Request):
    await instrument(request,symbol)
    if not hasattr(request.app.state,'depth'):
        raise HTTPException(503,detail='CACHE_UNAVAILABLE')
    try:
        return await asyncio.to_thread(request.app.state.depth.read,symbol)
    except (redis.RedisError,ValueError,TypeError):
        raise HTTPException(503,detail='CACHE_UNAVAILABLE') from None


@router.get('/{symbol}/trades')
async def trades(symbol: str,request: Request,limit: int=Query(50,ge=1,le=100),before_id: int=Query(2**63-1,gt=0)):
    row=await instrument(request,symbol)
    rows=await asyncio.to_thread(request.app.state.database.query,
        'SELECT * FROM execution WHERE instrument_id=%s AND id<%s ORDER BY id DESC LIMIT %s',(row['id'],before_id,limit))
    return {'items':rows,'next_before_id':rows[-1]['id'] if len(rows)==limit else None}


@router.get('/{symbol}/analytics')
async def analytics(symbol: str,request: Request,lower_ticks: int=Query(1,ge=0),upper_ticks: int=Query(2**53-1,ge=0)):
    row=await instrument(request,symbol)
    engine=request.app.state.service.engine
    value=engine.vwap[row['id']].value()
    return {'vwap_ticks':str(value) if value is not None else None,
            'window_fills':min(engine.window,engine.vwap[row['id']].count),
            'band_volume':engine.volume[row['id']].range_sum(lower_ticks,upper_ticks),
            'as_of':engine.latest_time.get(row['id'])}
