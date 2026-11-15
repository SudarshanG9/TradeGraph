from fastapi import HTTPException


def require_role(actor, role):
    if actor['role'] != role:
        raise HTTPException(403, detail='FORBIDDEN')
    return actor
