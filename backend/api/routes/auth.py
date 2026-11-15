import asyncio
import bcrypt
from typing import Literal
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from backend.auth.security import password_matches, issue_token

router = APIRouter()
DUMMY_HASH = bcrypt.hashpw(b'nonexistent-account', bcrypt.gensalt()).decode()


class Login(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=72)


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal['bearer']
    role: Literal['TRADER','COMPLIANCE_ADMIN']
    expires_in: int


@router.post('/login', response_model=LoginResponse)
async def login(body: Login, request: Request):
    db, settings = request.app.state.database, request.app.state.settings
    rows = await asyncio.to_thread(db.query, 'SELECT id,role,password_hash FROM user_account WHERE email=%s', (body.email,))
    row = rows[0] if rows else None
    valid = await asyncio.to_thread(password_matches, body.password, row['password_hash'] if row else DUMMY_HASH)
    if not valid or row is None:
        raise HTTPException(401, detail='UNAUTHORIZED')
    return {'access_token':issue_token(row['id'], row['role'], settings), 'token_type':'bearer', 'role':row['role'], 'expires_in':settings.jwt_ttl_seconds}
