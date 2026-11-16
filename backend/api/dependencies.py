import asyncio
import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from backend.auth.security import decode_token
from backend.auth.rbac import require_role

bearer = HTTPBearer(auto_error=False)


def service(request: Request):
    return request.app.state.service


async def actor(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
    if credentials is None:
        raise HTTPException(401, detail='UNAUTHORIZED')
    try:
        claims = decode_token(credentials.credentials, request.app.state.settings)
    except (jwt.PyJWTError, ValueError, TypeError, KeyError):
        raise HTTPException(401, detail='UNAUTHORIZED') from None
    identity = await asyncio.to_thread(request.app.state.database.identity, claims['sub'])
    if not identity or identity['role'] != claims['role']:
        raise HTTPException(401, detail='UNAUTHORIZED')
    state = await asyncio.to_thread(request.app.state.database.registration_status, identity['id'])
    if state is not None and state != 'ACTIVE':
        raise HTTPException(403, detail='REGISTRATION_' + state)
    return identity


async def trader(identity=Depends(actor)):
    require_role(identity, 'TRADER')
    if not identity['trader_id']:
        raise HTTPException(403, detail='FORBIDDEN')
    return identity


async def admin(identity=Depends(actor)):
    return require_role(identity, 'COMPLIANCE_ADMIN')
