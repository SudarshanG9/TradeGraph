"""Lazy environment settings for the native, single-process demonstration."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from getpass import getuser
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


class _Environment(dict):
    def __repr__(self):
        return '<environment settings redacted>'


def _secret(values: Mapping[str, str], name: str, minimum: int = 1) -> str:
    value = values.get(name, "")
    if len(value.strip()) < minimum or value.lower().startswith(("replace_", "change_me", "your_")):
        raise ValueError(f"{name} must contain a configured secret")
    return value


def _integer(values: Mapping[str, str], name: str, default: int,
             minimum: int, maximum: int) -> int:
    try:
        value = int(values.get(name, str(default)))
    except (TypeError, ValueError):
        raise ValueError(f"{name} must be an integer") from None
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} is outside the supported range")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_runtime_user: str
    postgres_runtime_password: str = field(repr=False)
    redis_url: str = field(repr=False)
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str = field(repr=False)
    jwt_secret: str = field(repr=False)
    jwt_algorithm: str
    jwt_ttl_seconds: int
    health_timeout_seconds: int
    health_interval_seconds: int
    event_queue_capacity: int
    service_workers: int
    maintenance_enabled: bool = False
    maintenance_interval_seconds: int = 60
    archive_age_seconds: int = 86400
    maintenance_batch_size: int = 100
    maintenance_retries: int = 3

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None,
                 *, env_file: Path | None = ROOT / ".env") -> Settings:
        """Explicit mappings are isolated; process env otherwise overrides .env.

        Import does not load secrets or connect. Setup/admin credentials are not
        runtime fallbacks. PG role attributes/grants require API startup checks.
        """
        if environ is None:
            values = _Environment({key: value for key, value in
                      (dotenv_values(env_file, interpolate=False) if env_file else {}).items()
                      if value is not None})
            values.update(os.environ)
        else:
            values = _Environment(environ)

        runtime_user = values.get("POSTGRES_RUNTIME_USER", "tradegraph_runtime").strip()
        forbidden_users = {"postgres", "tradegraph_owner", "trader_role", "compliance_admin_role", getuser()}
        forbidden_users.update(values.get(key, "") for key in ("POSTGRES_ADMIN_USER", "POSTGRES_USER"))
        if not runtime_user or runtime_user in forbidden_users:
            raise ValueError("POSTGRES_RUNTIME_USER must be a dedicated service login")
        host = values.get("POSTGRES_HOST", "/tmp").strip()
        database = values.get("POSTGRES_DB", "tradegraph").strip()
        neo4j_user = values.get("NEO4J_USER", "neo4j").strip()
        if not host or not database or not neo4j_user:
            raise ValueError("PostgreSQL host/database and Neo4j user must be nonempty")
        redis_url = values.get("REDIS_URL", "redis://127.0.0.1:6379/0")
        neo4j_uri = values.get("NEO4J_URI", "bolt://127.0.0.1:7687")
        for name, value, schemes in (
            ("REDIS_URL", redis_url, {"redis", "rediss"}),
            ("NEO4J_URI", neo4j_uri, {"bolt", "bolt+s", "bolt+ssc", "neo4j", "neo4j+s", "neo4j+ssc"}),
        ):
            try:
                parsed = urlsplit(value)
                valid = parsed.scheme in schemes and bool(parsed.hostname)
                if parsed.port is not None:
                    valid = valid and 0 < parsed.port <= 65535
                if name == "NEO4J_URI":
                    valid = valid and parsed.username is None and parsed.password is None
            except ValueError:
                valid = False
            if not valid:
                raise ValueError(f"{name} must be a supported service URL")
        algorithm = values.get("JWT_ALGORITHM", "HS256")
        if algorithm != "HS256":
            raise ValueError("JWT_ALGORITHM must be HS256 for contract version 1")
        if values.get('MAINTENANCE_ENABLED', 'false') not in ('true', 'false'):
            raise ValueError('MAINTENANCE_ENABLED must be true or false')
        workers = _integer(values, "SERVICE_WORKERS", 1, 1, 1)
        return cls(
            postgres_host=host,
            postgres_port=_integer(values, "POSTGRES_PORT", 5432, 1, 65535),
            postgres_db=database, postgres_runtime_user=runtime_user,
            postgres_runtime_password=_secret(values, "POSTGRES_RUNTIME_PASSWORD"),
            redis_url=redis_url, neo4j_uri=neo4j_uri, neo4j_user=neo4j_user,
            neo4j_password=_secret(values, "NEO4J_PASSWORD"),
            jwt_secret=_secret(values, "JWT_SECRET", 32), jwt_algorithm=algorithm,
            jwt_ttl_seconds=_integer(values, "JWT_TTL_SECONDS", 900, 60, 3600),
            health_timeout_seconds=_integer(values, "HEALTH_TIMEOUT_SECONDS", 3, 1, 30),
            health_interval_seconds=_integer(values, "HEALTH_INTERVAL_SECONDS", 10, 1, 300),
            event_queue_capacity=_integer(values, "EVENT_QUEUE_CAPACITY", 1024, 1, 100000),
            service_workers=workers,
            maintenance_enabled=values.get('MAINTENANCE_ENABLED', 'false') == 'true',
            maintenance_interval_seconds=_integer(values,'MAINTENANCE_INTERVAL_SECONDS',60,10,3600),
            archive_age_seconds=_integer(values,'ARCHIVE_AGE_SECONDS',86400,3600,31536000),
            maintenance_batch_size=_integer(values,'MAINTENANCE_BATCH_SIZE',100,1,10000),
            maintenance_retries=_integer(values,'MAINTENANCE_RETRIES',3,1,5),
        )
