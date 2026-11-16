"""Server-only trader credentials; database session_user is the RLS identity."""
import json
import os
from pathlib import Path
from uuid import UUID
import psycopg


def trader_role(trader_id):
    return 'tg_' + str(UUID(str(trader_id)))


def credentials(path, trader_id):
    try:
        source=Path(path)
        info=source.stat()
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('Private credential file required')
        entry=json.loads(source.read_text())['traders'][str(UUID(str(trader_id)))]
        if entry['user'] != trader_role(trader_id) or len(entry['password'])<16:
            raise ValueError('Unbound credential')
        return entry['user'],entry['password']
    except (OSError,ValueError,KeyError,TypeError):
        raise psycopg.OperationalError('Trusted trader database identity unavailable') from None


def verify_password_authentication(host,port,database,user):
    """Wrong passwords must fail: trust authentication cannot bind tenant identity."""
    import secrets
    try:
        connection=psycopg.connect(host=host,port=port,dbname=database,user=user,
            password=secrets.token_urlsafe(48),connect_timeout=3)
    except psycopg.errors.InvalidPassword:
        return True
    except psycopg.Error as exc:
        # libpq connection handshakes may omit SQLSTATE on OperationalError.
        # Accept only PostgreSQL's explicit password rejection; network, TLS,
        # missing service and all other failures remain unverified/fail-closed.
        if exc.sqlstate=='28P01' or 'password authentication failed for user' in str(exc):
            return True
        raise RuntimeError('Database password authentication could not be verified') from None
    connection.close()
    raise RuntimeError('Database accepts incorrect passwords; trusted identity unavailable')
