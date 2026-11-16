import asyncio
import bcrypt
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
import psycopg
from backend.stores.registration import Registration, register_account, normalize_email
from backend.auth.security import password_matches, issue_token

router = APIRouter()
DUMMY_HASH = bcrypt.hashpw(b'nonexistent-account', bcrypt.gensalt()).decode()


class Login(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=72)

    @field_validator('email')
    @classmethod
    def normalize(cls, value):
        return normalize_email(value)

    @field_validator('password')
    @classmethod
    def byte_length(cls, value):
        if len(value.encode())>72 or '\x00' in value: raise ValueError('Password exceeds supported byte length')
        return value


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal['bearer']
    role: Literal['TRADER','COMPLIANCE_ADMIN']
    expires_in: int


@router.post('/login', response_model=LoginResponse)
async def login(body: Login, request: Request):
    db, settings = request.app.state.database, request.app.state.settings
    rows = await asyncio.to_thread(db.auth_query, 'SELECT id,role,password_hash FROM user_account WHERE lower(btrim(email))=%s', (body.email,))
    row = rows[0] if rows else None
    valid = await asyncio.to_thread(password_matches, body.password, row['password_hash'] if row else DUMMY_HASH)
    if not valid or row is None:
        raise HTTPException(401, detail='UNAUTHORIZED')
    state = await asyncio.to_thread(db.registration_status, row['id'])
    if state is not None and state != 'ACTIVE':
        raise HTTPException(403, detail='REGISTRATION_' + state)
    return {'access_token':issue_token(row['id'], row['role'], settings), 'token_type':'bearer', 'role':row['role'], 'expires_in':settings.jwt_ttl_seconds}


class RegistrationReceipt(BaseModel):
    registration_id: str
    status: Literal['PENDING_VERIFICATION','PENDING_PROVISIONING','ACTIVE']


@router.post('/register', response_model=RegistrationReceipt, status_code=201)
async def register(body: Registration, request: Request):
    try:
        result = await asyncio.to_thread(register_account, request.app.state.database, body)
    except psycopg.errors.UniqueViolation:
        raise HTTPException(409, detail='REGISTRATION_EXISTS') from None
    return {'registration_id':str(result['registration_id']), 'status':result['status']}
