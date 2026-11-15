#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
"${PYTHON:-.venv/bin/python}" - "$@" <<'PY'
import argparse
from pathlib import Path
from scripts.verify_schema import db_connect, EXPECTED_TABLES

parser = argparse.ArgumentParser(description='Incremental native backend installation; no bootstrap or seeds')
parser.add_argument('--phase', type=int, default=2, choices=[2])
args = parser.parse_args()
with db_connect() as conn:
    conn.execute("SELECT pg_advisory_xact_lock(hashtext('tradegraph-backend-install'))")
    tables = {r[0] for r in conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
    if tables != EXPECTED_TABLES:
        raise SystemExit('Expected the initialized 13-table schema; refusing installation')
    signature = 'public.place_and_reserve_order(uuid,integer,text,bigint,bigint)'
    if conn.execute('SELECT to_regprocedure(%s)', (signature,)).fetchone()[0] is None:
        sql = Path('db/procedures/place_and_reserve_order.sql').read_text().strip()
        sql = sql.removeprefix('BEGIN;').removesuffix('COMMIT;')
        conn.execute(sql, prepare=False)
        print('Installed existing reservation function')
    else:
        print('Reservation already installed; preserved existing function')
print('Incremental Phase 2 installation committed; existing rows preserved')
PY
