#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

if [[ ! -f .env ]] || ! git check-ignore -q .env; then
  echo 'Create an ignored .env from .env.example before running setup.' >&2
  exit 1
fi

if ! python -c 'import psycopg, bcrypt, dotenv, pytest'; then
  echo 'Activate the virtual environment and install requirements.txt.' >&2
  exit 1
fi

echo 'Checking native PostgreSQL and applying the schema and reference rows atomically'
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
} | python -c '
import sys

import psycopg

from scripts.verify_schema import db_connect

try:
    with db_connect() as conn:
        conn.execute(sys.stdin.read(), prepare=False)
except psycopg.Error as exc:
    raise SystemExit(f"Day 1 database setup failed: {exc}") from None
'

python scripts/seed_demo_accounts.py
python scripts/verify_schema.py
python -m pytest -m day1 tests/integration/test_database_integrity.py tests/integration/test_rbac.py

echo 'Day 1 PostgreSQL setup and checks passed.'
