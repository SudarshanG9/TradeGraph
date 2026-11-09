from __future__ import annotations

import hashlib
import os
import warnings
from getpass import GetPassWarning, getpass
from pathlib import Path

import bcrypt
import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def db_connect():
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=10,
    )


def create_or_reuse_user(cur, email: str, role: str, password: str):
    cur.execute("SELECT id, role FROM user_account WHERE email=%s", (email,))
    found = cur.fetchone()
    if found is None:
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
        cur.execute(
            """INSERT INTO user_account(email,password_hash,role)
               VALUES (%s,%s,%s) ON CONFLICT (email) DO NOTHING RETURNING id""",
            (email, hashed, role),
        )
        created = cur.fetchone()
        if created is not None:
            return created[0], True
        cur.execute("SELECT id, role FROM user_account WHERE email=%s", (email,))
        found = cur.fetchone()

    if found is None or found[1] != role:
        raise ValueError(f"Could not reuse {email} as {role}")
    return found[0], False


def main():
    print("TradeGraph: synthetic Day 1 accounts (no real credentials/PANs)")
    with warnings.catch_warnings():
        warnings.simplefilter("error", GetPassWarning)
        try:
            traders_password = getpass("Trader demo password (12+ characters): ")
            admin_password = getpass("Compliance admin password (12+ characters): ")
        except GetPassWarning:
            raise SystemExit("Run the demo seeder in an interactive terminal.") from None
    if len(traders_password) < 12 or len(admin_password) < 12:
        raise ValueError("Both demo passwords must have at least 12 characters")
    if any(len(password.encode("utf-8")) > 72 for password in (traders_password, admin_password)):
        raise ValueError("Demo passwords must fit within bcrypt's 72-byte limit")
    if traders_password == admin_password:
        raise ValueError("Trader and administrator demo passwords must differ")

    trader_specs = [
        ("alice@tradegraph.test", "Alice"),
        ("bob@tradegraph.test", "Bob"),
        ("carol@tradegraph.test", "Carol"),
    ]
    new_accounts = 0
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM desk WHERE name='Equities'")
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("Run db/seed.sql first: Equities desk missing")
            desk_id = row[0]

            cur.execute("SELECT id FROM fee_tier WHERE tier_name='STANDARD'")
            row = cur.fetchone()
            if row is None:
                raise RuntimeError("Run db/seed.sql first: STANDARD fee tier missing")
            tier_id = row[0]
            alice_id = None

            for email, name in trader_specs:
                account_id, new = create_or_reuse_user(
                    cur, email, "TRADER", traders_password
                )
                new_accounts += int(new)
                cur.execute(
                    """INSERT INTO trader(user_account_id, desk_id, full_name)
                       VALUES (%s,%s,%s)
                       ON CONFLICT (user_account_id) DO NOTHING""",
                    (account_id, desk_id, name),
                )
                cur.execute("SELECT id FROM trader WHERE user_account_id=%s", (account_id,))
                trader_id = cur.fetchone()[0]
                if name == "Alice":
                    alice_id = trader_id

                cur.execute(
                    """INSERT INTO margin_account
                       (trader_id,cash_balance,escrow_balance,fee_tier_id)
                       VALUES (%s,%s,0,%s)
                       ON CONFLICT (trader_id) DO NOTHING""",
                    (trader_id, 10_000_000, tier_id),
                )
                fake_kyc = hashlib.sha256(
                    f"synthetic-demo-{trader_id}".encode()
                ).hexdigest()
                cur.execute(
                    """INSERT INTO kyc_profile(trader_id,pan_hash)
                       VALUES (%s,%s)
                       ON CONFLICT (trader_id) DO NOTHING""",
                    (trader_id, fake_kyc),
                )

            if alice_id is not None:
                cur.execute(
                    """UPDATE desk SET manager_trader_id=%s
                       WHERE id=%s AND manager_trader_id IS NULL""",
                    (alice_id, desk_id),
                )

            _, new = create_or_reuse_user(
                cur, "admin@tradegraph.test", "COMPLIANCE_ADMIN", admin_password
            )
            new_accounts += int(new)

    print(f"Seed succeeded; newly created user accounts: {new_accounts}")
    print("Existing account passwords and account balances were not changed")


if __name__ == "__main__":
    main()
