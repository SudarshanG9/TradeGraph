"""Authenticated catalog of actual tradable instrument metadata."""
import asyncio

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from backend.api.dependencies import actor

router = APIRouter(dependencies=[Depends(actor)], tags=['instruments'])
CATALOG_SQL = '''SELECT id,symbol,tick_size,lot_size,is_active
    FROM instrument WHERE is_active = TRUE ORDER BY symbol,id'''


class InstrumentInfo(BaseModel):
    id: int = Field(gt=0)
    symbol: str
    tick_size: int = Field(gt=0)
    lot_size: int = Field(gt=0)
    is_active: bool


class InstrumentCatalog(BaseModel):
    items: list[InstrumentInfo]


@router.get('/instruments', response_model=InstrumentCatalog)
async def list_instruments(request: Request):
    rows = await asyncio.to_thread(request.app.state.database.query, CATALOG_SQL)
    return {'items': rows}
