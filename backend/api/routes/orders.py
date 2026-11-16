import asyncio
from datetime import datetime
from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Depends, Request, HTTPException, Query, Header
from pydantic import BaseModel, ConfigDict, Field
from backend.api.dependencies import trader
from backend.risk.order_reservation import DuplicateRequest

router = APIRouter()


class NewOrder(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    instrument_id: int = Field(gt=0, le=2**31-1)
    side: Literal['BUY','SELL']
    price_ticks: int = Field(gt=0, le=2**63-1)
    quantity: int = Field(gt=0, le=2**63-1)


class AcceptedOrder(BaseModel):
    order_id: int
    status: Literal['OPEN']
    accepted_at: datetime


class OrderSummary(BaseModel):
    id: int
    trader_id: UUID
    instrument_id: int
    side: Literal['BUY','SELL']
    price_ticks: int
    quantity: int
    filled_quantity: int
    status: Literal['OPEN','PARTIAL','FILLED','CANCELLED']
    created_at: datetime
    updated_at: datetime
    archived: bool


class OwnOrders(BaseModel):
    items: list[OrderSummary]
    next_before_id: int | None


class Position(BaseModel):
    instrument_id: int
    net_quantity: int
    realized_pnl: int
    pnl_basis: Literal['gross']


class Account(BaseModel):
    trader_id: UUID
    cash_balance: int
    escrow_balance: int
    positions: list[Position]


class CancelledOrder(BaseModel):
    order_id: int
    status: Literal['CANCELLED']
    cancelled_quantity: int


@router.post('/orders', status_code=201, response_model=AcceptedOrder)
async def submit(body: NewOrder, request: Request, identity=Depends(trader),
                 idempotency_key: str | None=Header(None,min_length=1,max_length=128,pattern=r'^[A-Za-z0-9._-]+$')):
    try:
        row = await request.app.state.service.admit(identity['trader_id'], body,idempotency_key)
    except DuplicateRequest:
        raise HTTPException(409,detail='DUPLICATE_REQUEST') from None
    except ValueError:
        raise HTTPException(422, detail='INVALID_ORDER') from None
    except RuntimeError:
        raise HTTPException(503, detail='TRADING_UNAVAILABLE') from None
    return {'order_id':row['id'], 'status':'OPEN', 'accepted_at':row['created_at']}


@router.post('/orders/{order_id}/cancel',response_model=CancelledOrder)
async def cancel(order_id: int, request: Request, identity=Depends(trader)):
    try:
        quantity = await request.app.state.service.cancel(order_id,identity['trader_id'])
    except LookupError:
        raise HTTPException(404, detail='ORDER_NOT_FOUND') from None
    except ValueError:
        raise HTTPException(409, detail='ORDER_TERMINAL') from None
    except RuntimeError:
        raise HTTPException(503, detail='TRADING_UNAVAILABLE') from None
    return {'order_id':order_id,'status':'CANCELLED','cancelled_quantity':quantity}


@router.get('/orders/me', response_model=OwnOrders)
async def own_orders(request: Request, limit: int = Query(50, ge=1, le=100), before_id: int = Query(2**63-1, gt=0), identity=Depends(trader)):
    rows = await asyncio.to_thread(request.app.state.database.trader_query, identity['trader_id'],
        'SELECT *,false AS archived FROM public."order" WHERE trader_id=%s AND id<%s UNION ALL SELECT id,trader_id,instrument_id,side,price_ticks,quantity,filled_quantity,status,created_at,updated_at,true AS archived FROM order_history WHERE trader_id=%s AND id<%s ORDER BY id DESC LIMIT %s',
        (identity['trader_id'],before_id,identity['trader_id'],before_id,limit))
    return {'items':rows,'next_before_id':rows[-1]['id'] if len(rows)==limit else None}


@router.get('/account/me', response_model=Account)
async def account(request: Request, identity=Depends(trader)):
    snapshot=await asyncio.to_thread(request.app.state.database.account_snapshot,identity['trader_id'])
    if snapshot is None:raise HTTPException(404,detail='ACCOUNT_NOT_FOUND')
    return snapshot


class RequestOutcome(BaseModel):
    trader_id: UUID
    status: Literal['ACCEPTED', 'UNRESOLVED']
    accepted_order: AcceptedOrder | None


@router.get('/orders/requests/{request_key}', response_model=RequestOutcome)
async def request_outcome(request_key: str, request: Request, identity=Depends(trader)):
    # Read-only and always scoped to the authenticated server-derived trader.
    import re
    if not re.fullmatch(r'[A-Za-z0-9._-]{1,128}', request_key):
        raise HTTPException(422, detail='INVALID_REQUEST')
    row = await asyncio.to_thread(request.app.state.database.trader_request_identity, identity['trader_id'], request_key)
    return {'trader_id':identity['trader_id'], 'status':'ACCEPTED' if row else 'UNRESOLVED',
            'accepted_order':{'order_id':row['order_id'], 'status':'OPEN', 'accepted_at':row['accepted_at']} if row else None}


@router.get('/orders/{order_id}', response_model=OrderSummary)
async def owned_order(order_id: int, request: Request, identity=Depends(trader)):
    service = request.app.state.service
    # A read serialized after shielded cancellation and all preceding settlement
    # establishes whether an active order is safe to cancel again. A bare history
    # page cannot certify that no cancellation thread is still in flight.
    async with service.lock:
        async def read():
            rows = await asyncio.to_thread(request.app.state.database.trader_query, identity['trader_id'],
                'SELECT *,false AS archived FROM public."order" WHERE id=%s AND trader_id=%s UNION ALL SELECT id,trader_id,instrument_id,side,price_ticks,quantity,filled_quantity,status,created_at,updated_at,true AS archived FROM order_history WHERE id=%s AND trader_id=%s',
                (order_id,identity['trader_id'],order_id,identity['trader_id']))
            if len(rows) != 1:
                raise HTTPException(404, detail='ORDER_NOT_FOUND')
            return rows[0]
        row = await read()
        # Terminal canonical state certifies the financial outcome even while a
        # separate pipeline failure remains closed. Never reset that failure here.
        if row['status'] in ('FILLED','CANCELLED'):
            return row
        if service.closing or service.dispatcher.failure or not service.worker:
            raise HTTPException(503, detail='TRADING_UNAVAILABLE')
        try:
            await service.worker.drain()
            await asyncio.to_thread(service.verify_owner)
        except Exception:
            raise HTTPException(503, detail='TRADING_UNAVAILABLE') from None
        return await read()
