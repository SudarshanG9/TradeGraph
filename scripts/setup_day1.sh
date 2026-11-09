#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]] || ! git check-ignore -q .env; then
  echo 'Create an ignored .env from .env.example before running setup.' >&2
  exit 1
fi

if ! docker info >/dev/null; then
  echo 'Docker Engine is unavailable. Check Docker Desktop and run docker info.' >&2
  exit 1
fi

if ! python -c 'import psycopg, bcrypt, dotenv, pytest'; then
  echo 'Activate the virtual environment and install requirements.txt.' >&2
  exit 1
fi

docker compose config --quiet
docker compose up -d --no-recreate --wait --wait-timeout 90

# The image's temporary initialization server only listens on its Unix socket.
postgres_ready() {
  docker compose exec -T postgres sh -c \
    'pg_isready -h 127.0.0.1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null
}

for _ in $(seq 1 30); do
  if postgres_ready; then break; fi
  sleep 2
done
if ! postgres_ready; then
  echo 'PostgreSQL did not start listening over TCP.' >&2
  exit 1
fi

psql_local() {
  docker compose exec -T postgres sh -c \
    'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' psql "$@"
}

echo 'Checking PostgreSQL and applying the schema and reference rows atomically'
{
  cat <<'SQL'
SELECT pg_advisory_xact_lock(hashtext('tradegraph-day1-bootstrap'));
DO $$
DECLARE
    existing_tables text;
BEGIN
    SELECT string_agg(tablename, ', ' ORDER BY tablename) INTO existing_tables
    FROM pg_tables WHERE schemaname = 'public';
    IF existing_tables IS NOT NULL THEN
        RAISE EXCEPTION 'Day 1 setup requires a fresh database. Existing tables: %', existing_tables;
    END IF;
END $$;
SQL
  cat db/schema.sql db/seed.sql
} | psql_local --single-transaction --file=-

python scripts/seed_demo_accounts.py
python scripts/verify_schema.py
python -m pytest -m day1 tests/integration/test_database_integrity.py tests/integration/test_rbac.py

if [[ $(docker compose exec -T redis redis-cli ping) != PONG ]]; then
  echo 'Redis did not return PONG.' >&2
  exit 1
fi
echo 'Redis PONG'

for _ in $(seq 1 30); do
  if docker compose exec -T neo4j sh -c \
    'cypher-shell -u neo4j -p "${NEO4J_AUTH#neo4j/}" "RETURN 1 AS success;"' 2>/dev/null; then
    echo 'Day 1 setup and runtime checks passed.'
    exit 0
  fi
  sleep 3
done
echo 'Neo4j Cypher connection failed.' >&2
exit 1
