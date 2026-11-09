import os
from pathlib import Path

import psycopg
import pytest
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


@pytest.fixture
def db_conn():
    # Local test connection only. Every test is rolled back, pass or fail.
    conn = psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=10,
        autocommit=False,
    )
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
