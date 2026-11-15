from datetime import datetime, timedelta, timezone
from uuid import UUID
import bcrypt
import jwt


def password_matches(password, hashed):
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


def issue_token(subject, role, settings):
    now = datetime.now(timezone.utc)
    return jwt.encode({'sub':str(subject), 'role':role, 'iat':now,
        'exp':now+timedelta(seconds=settings.jwt_ttl_seconds)}, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token, settings):
    claims = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm],
        options={'require':['sub','role','iat','exp']})
    UUID(claims['sub'])
    if claims['role'] not in ('TRADER','COMPLIANCE_ADMIN'):
        raise ValueError('Invalid role')
    return claims
