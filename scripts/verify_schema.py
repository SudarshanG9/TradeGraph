from __future__ import annotations

import os
import sys
from getpass import getuser
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

EXPECTED_TABLES = {
    "user_account", "desk", "trader", "kyc_profile", "fee_tier",
    "margin_account", "instrument", "order", "order_history", "execution",
    "position", "market_disclosure", "regime_snapshot",
}
EXPECTED_ROLES = {"trader_role", "compliance_admin_role"}
EXPECTED_POLICIES = {
    ("market_disclosure", "disclosure_admin_only"),
    ("regime_snapshot", "regime_admin_only"),
}
EXPECTED_INDEXES = {
    "idx_order_instrument_side_price",
    "idx_order_trader_time",
    "idx_order_history_trader_time",
    "idx_execution_instrument_time",
    "idx_execution_buy_trader",
    "idx_execution_sell_trader",
    "idx_disclosure_tsv",
    "idx_regime_hnsw",
}


def assert_ok(condition: bool, description: str):
    if not condition:
        raise AssertionError(description)
    print("PASS:", description)


def db_connect():
    return psycopg.connect(
        host=os.getenv("POSTGRES_ADMIN_HOST", "/tmp"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.getenv("POSTGRES_DB", "tradegraph"),
        user=os.getenv("POSTGRES_ADMIN_USER") or getuser(),
        connect_timeout=10,
    )


def main():
    with db_connect() as conn:
        conn.read_only = True
        with conn.cursor() as cur:
            cur.execute(
                """SELECT table_name FROM information_schema.tables
                   WHERE table_schema='public' AND table_type='BASE TABLE'"""
            )
            tables = {r[0] for r in cur.fetchall()}
            assert_ok(tables == EXPECTED_TABLES,
                      f"Exactly 13 application tables (found: {sorted(tables)})")

            cur.execute(
                """SELECT rolname FROM pg_roles
                   WHERE rolname IN ('trader_role', 'compliance_admin_role')
                     AND NOT rolcanlogin AND NOT rolsuper AND NOT rolbypassrls"""
            )
            roles = {r[0] for r in cur.fetchall()}
            assert_ok(roles == EXPECTED_ROLES, "Both NOLOGIN application roles subject to RLS")

            cur.execute(
                """SELECT extname FROM pg_extension
                   WHERE extname IN ('vector','pgcrypto')"""
            )
            assert_ok({r[0] for r in cur.fetchall()} == {"vector", "pgcrypto"},
                      "vector and pgcrypto extensions")

            cur.execute(
                """SELECT tablename, policyname, roles = ARRAY['compliance_admin_role']::name[]
                   FROM pg_policies WHERE schemaname='public'"""
            )
            assert_ok(
                set(cur.fetchall()) == {(table, policy, True) for table, policy in EXPECTED_POLICIES},
                "Two admin RLS policies",
            )

            cur.execute(
                """SELECT relname, relrowsecurity, relforcerowsecurity
                   FROM pg_class WHERE relnamespace='public'::regnamespace AND relname IN
                        ('market_disclosure','regime_snapshot')"""
            )
            security = {name: (enabled, forced) for name, enabled, forced in cur.fetchall()}
            assert_ok(
                security == {
                    "market_disclosure": (True, True),
                    "regime_snapshot": (True, True),
                },
                "RLS enabled and forced on both admin tables",
            )

            cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname='public'")
            missing_indexes = EXPECTED_INDEXES - {r[0] for r in cur.fetchall()}
            if missing_indexes:
                raise AssertionError(f"Missing indexes: {', '.join(sorted(missing_indexes))}")
            print("PASS: Required order, execution, GIN, HNSW indexes")

            cur.execute(
                """SELECT pg_get_constraintdef(oid) FROM pg_constraint
                   WHERE conrelid='public.position'::regclass AND contype='p'"""
            )
            definition = cur.fetchone()
            assert_ok(definition is not None and
                      "(trader_id, instrument_id)" in definition[0],
                      "Composite position primary key")

            cur.execute(
                """SELECT count(*) FROM pg_constraint
                   WHERE contype='f' AND connamespace='public'::regnamespace"""
            )
            fk_count = cur.fetchone()[0]
            assert_ok(fk_count == 18, f"18 foreign key relationships (found {fk_count})")

            cur.execute(
                """SELECT column_default FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='order_history'
                     AND column_name='id'"""
            )
            row = cur.fetchone()
            assert_ok(row is not None and row[0] is None,
                      "Archive IDs are preserved (no independent ID default)")

            cur.execute("SELECT to_regclass('public._scratch_migration_test')")
            assert_ok(cur.fetchone()[0] is None, "Scratch DROP TABLE completed")

            expected_counts = {
                "user_account": 4, "trader": 3, "kyc_profile": 3,
                "margin_account": 3, "fee_tier": 2,
                "instrument": 3, "desk": 2,
            }
            for table, minimum in expected_counts.items():
                # Only the fixed, trusted table list above is interpolated.
                cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                actual = cur.fetchone()[0]
                assert_ok(actual >= minimum, f"{table}: at least {minimum} rows ({actual})")

            cur.execute(
                """SELECT count(*) FROM desk child JOIN desk parent
                     ON child.parent_desk_id=parent.id
                   WHERE child.name='Equities' AND parent.name='Global Trading'"""
            )
            assert_ok(cur.fetchone()[0] == 1, "Recursive desk relationship seeded")

            cur.execute(
                """SELECT count(*) FROM desk d JOIN trader t
                     ON d.manager_trader_id=t.id
                   WHERE d.name='Equities' AND t.full_name='Alice'"""
            )
            assert_ok(cur.fetchone()[0] == 1, "Desk manager seeded")

            cur.execute(
                r"""SELECT count(*) FROM user_account
                   WHERE password_hash ~ '^\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}$'
                     AND ((role='TRADER' AND email IN (
                           'alice@tradegraph.test', 'bob@tradegraph.test', 'carol@tradegraph.test'))
                          OR (role='COMPLIANCE_ADMIN' AND email='admin@tradegraph.test'))"""
            )
            assert_ok(cur.fetchone()[0] == 4, "Four demo accounts with expected roles and bcrypt hashes")

            cur.execute(
                """SELECT count(*) FROM user_account u
                   JOIN trader t ON t.user_account_id=u.id
                   JOIN margin_account m ON m.trader_id=t.id
                   JOIN kyc_profile k ON k.trader_id=t.id
                   WHERE u.email IN ('alice@tradegraph.test', 'bob@tradegraph.test',
                                     'carol@tradegraph.test')"""
            )
            assert_ok(cur.fetchone()[0] == 3, "All three demo traders have margin and KYC records")

            cur.execute(
                """SELECT has_table_privilege('trader_role',
                   'public.market_disclosure','SELECT')"""
            )
            assert_ok(cur.fetchone()[0] is False, "Trader has no disclosure SELECT grant")

            cur.execute(
                """SELECT has_table_privilege('trader_role',
                   'public.margin_account','UPDATE')"""
            )
            assert_ok(cur.fetchone()[0] is False, "Trader cannot directly update balances")

            cur.execute(
                """SELECT has_table_privilege('compliance_admin_role',
                   'public.market_disclosure','SELECT')"""
            )
            assert_ok(cur.fetchone()[0] is True, "Compliance administrator has disclosure grant")

    print("\nDAY 1 READ-ONLY VERIFICATION PASSED")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(1)
