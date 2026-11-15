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
    rows = await asyncio.to_thread(request.app.state.database.query,
        'SELECT *,false AS archived FROM public."order" WHERE trader_id=%s AND id<%s UNION ALL SELECT id,trader_id,instrument_id,side,price_ticks,quantity,filled_quantity,status,created_at,updated_at,true AS archived FROM order_history WHERE trader_id=%s AND id<%s ORDER BY id DESC LIMIT %s',
        (identity['trader_id'],before_id,identity['trader_id'],before_id,limit))
    return {'items':rows,'next_before_id':rows[-1]['id'] if len(rows)==limit else None}


@router.get('/account/me', response_model=Account)
async def account(request: Request, identity=Depends(trader)):
    db = request.app.state.database
    rows = await asyncio.to_thread(db.query, 'SELECT trader_id,cash_balance,escrow_balance FROM margin_account WHERE trader_id=%s', (identity['trader_id'],))
    if not rows:
        raise HTTPException(404, detail='ACCOUNT_NOT_FOUND')
    positions = await asyncio.to_thread(db.query, "SELECT instrument_id,net_quantity,realized_pnl,'gross' AS pnl_basis FROM position WHERE trader_id=%s", (identity['trader_id'],))
    return rows[0] | {'positions':positions}
