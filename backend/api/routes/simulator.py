"""Additive administrator-only contract for the process-local live market."""
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.api.dependencies import admin
from backend.simulator.live_supervisor import (
    LiveSimulationConfig, SimulationConflict, SimulationUnavailable,
)

InstrumentID = Annotated[int, Field(strict=True, gt=0, le=2**31 - 1)]


class ErrorDetail(BaseModel):
    code: str
    message: str


class SimulatorError(BaseModel):
    error: ErrorDetail


router = APIRouter(prefix='/admin/simulator', dependencies=[Depends(admin)], responses={
    401: {'model': SimulatorError, 'description': 'Missing or invalid authentication'},
    403: {'model': SimulatorError, 'description': 'Compliance Administrator role required'},
})


class SimulationStart(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    instrument_ids: list[InstrumentID] = Field(min_length=1, max_length=3)
    bot_count: int = Field(default=8, ge=4, le=8)
    orders_per_second: int = Field(default=2, ge=1, le=5)
    volatility: Literal['low', 'medium', 'high'] = 'medium'
    seed: int = Field(default=20261115, ge=0, le=2**63 - 1)
    max_duration_seconds: int = Field(default=300, ge=30, le=600)

    @field_validator('instrument_ids')
    @classmethod
    def unique_instruments(cls, values):
        if len(set(values)) != len(values):
            raise ValueError('Instruments must be unique')
        return values


class SimulationStatus(BaseModel):
    run_id: str | None
    state: Literal['STOPPED', 'RUNNING', 'STOPPING', 'ERROR']
    started_at: datetime | None
    stopped_at: datetime | None
    active_bots: int
    instrument_ids: list[int]
    config: SimulationStart | None
    orders_attempted: int
    orders_accepted: int
    orders_rejected: int
    orders_cancelled: int
    backpressure_events: int
    active_bot_orders: int
    committed_executions: int
    last_action_at: datetime | None
    last_error: str | None
    derived_workers: dict[str, Literal['ready', 'retrying', 'initializing']]


def supervisor(request):
    return request.app.state.live_simulator


@router.post('/start', response_model=SimulationStatus, responses={
    409: {'model': SimulatorError, 'description': 'Session conflict or unresolved bot orders'},
    422: {'model': SimulatorError, 'description': 'Invalid configuration or inactive/unknown instrument'},
    503: {'model': SimulatorError, 'description': 'Trading unavailable or bot accounts not provisioned'},
})
async def start(body: SimulationStart, request: Request):
    try:
        config = LiveSimulationConfig(**(body.model_dump() | {'instrument_ids': tuple(body.instrument_ids)}))
        result = await supervisor(request).start(config)
    except SimulationConflict as exc:
        raise HTTPException(409, detail=str(exc)) from None
    except SimulationUnavailable:
        raise HTTPException(503, detail='TRADING_UNAVAILABLE') from None
    except ValueError as exc:
        if str(exc) == 'BOT_ACCOUNTS_NOT_PROVISIONED':
            raise HTTPException(503, detail='BOT_ACCOUNTS_NOT_PROVISIONED') from None
        raise HTTPException(422, detail='INVALID_SIMULATION_CONFIG') from None
    # Dataclass tuples are converted to the public JSON list contract.
    result['config']['instrument_ids'] = list(body.instrument_ids)
    return result


@router.post('/stop', response_model=SimulationStatus)
async def stop(request: Request):
    result = await supervisor(request).stop()
    if result['config']:
        result['config']['instrument_ids'] = list(result['instrument_ids'])
    return result


@router.get('/status', response_model=SimulationStatus, responses={
    503: {'model': SimulatorError, 'description': 'Database unavailable or order reconciliation required'},
})
async def status(request: Request):
    try:
        result = await supervisor(request).status()
    except SimulationUnavailable:
        raise HTTPException(503, detail='SIMULATOR_RECONCILIATION_REQUIRED') from None
    if result['config']:
        result['config']['instrument_ids'] = list(result['instrument_ids'])
    return result


@router.post('/recover', response_model=SimulationStatus)
async def recover(request: Request):
    try:
        return await supervisor(request).recover()
    except SimulationConflict as exc:
        raise HTTPException(409,detail=str(exc)) from None
    except (SimulationUnavailable, RuntimeError):
        raise HTTPException(503,detail='SIMULATOR_RECONCILIATION_REQUIRED') from None
