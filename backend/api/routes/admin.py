import asyncio
from typing import Literal
from fastapi import APIRouter,Depends,Request,Query,HTTPException
from backend.api.dependencies import admin

router=APIRouter(prefix='/admin',dependencies=[Depends(admin)])


@router.get('/surveillance/cycles')
async def cycles(request: Request,limit: int=Query(25,ge=1,le=100)):
    if not hasattr(request.app.state,'graph'):
        raise HTTPException(503,detail='GRAPH_UNAVAILABLE')
    try:
        return {'candidates':await asyncio.to_thread(request.app.state.graph.cycles,limit)}
    except Exception:
        raise HTTPException(503,detail='GRAPH_UNAVAILABLE') from None


@router.get('/desks/rollup')
async def rollup(request: Request):
    return {'items':await asyncio.to_thread(request.app.state.database.named,'rollup')}


@router.get('/optimizer/compare')
async def optimizer(request: Request, scenario: Literal['price_band','recent_executions']='price_band',
                    instrument_id: int=Query(1,gt=0), lower_ticks: int=Query(1,gt=0),upper_ticks: int=Query(2**53-1,gt=0)):
    return await asyncio.to_thread(request.app.state.database.optimizer,scenario,instrument_id,lower_ticks,upper_ticks)
