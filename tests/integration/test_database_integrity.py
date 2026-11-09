import pytest
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation

pytestmark = pytest.mark.day1


def test_thirteen_tables(db_conn):
    with db_conn.cursor() as cur:
        cur.execute(
            """SELECT count(*) FROM information_schema.tables
               WHERE table_schema='public' AND table_type='BASE TABLE'"""
        )
        assert cur.fetchone()[0] == 13


def test_static_seeds_and_hierarchy(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM instrument")
        assert cur.fetchone()[0] == 3
        cur.execute("SELECT count(*) FROM fee_tier")
        assert cur.fetchone()[0] == 2
        cur.execute(
            """SELECT parent.name FROM desk child
               JOIN desk parent ON child.parent_desk_id = parent.id
               WHERE child.name = 'Equities'"""
        )
        assert cur.fetchone()[0] == "Global Trading"


def test_invalid_tick_size_rejected(db_conn):
    with db_conn.cursor() as cur, pytest.raises(CheckViolation):
        cur.execute(
            "INSERT INTO instrument(symbol,tick_size,lot_size) VALUES (%s,%s,%s)",
            ("BAD_TICK", -1, 1),
        )


def test_invalid_user_role_rejected(db_conn):
    with db_conn.cursor() as cur, pytest.raises(CheckViolation):
        cur.execute(
            "INSERT INTO user_account(email,password_hash,role) VALUES (%s,%s,%s)",
            ("invalid@tradegraph.test", "not-a-hash", "ROOT"),
        )


def test_negative_balance_rejected(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT trader_id FROM margin_account LIMIT 1")
        trader_id = cur.fetchone()[0]
        with pytest.raises(CheckViolation):
            cur.execute(
                "UPDATE margin_account SET cash_balance=-1 WHERE trader_id=%s",
                (trader_id,),
            )


def test_invalid_trader_fk_rejected(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM instrument LIMIT 1")
        instrument_id = cur.fetchone()[0]
        with pytest.raises(ForeignKeyViolation):
            cur.execute(
                """INSERT INTO "order"
                   (trader_id,instrument_id,side,price_ticks,quantity)
                   VALUES (%s,%s,'BUY',100,1)""",
                ("00000000-0000-0000-0000-000000000000", instrument_id),
            )


def test_duplicate_instrument_symbol_rejected(db_conn):
    with db_conn.cursor() as cur, pytest.raises(UniqueViolation):
        cur.execute(
            "INSERT INTO instrument(symbol,tick_size,lot_size) VALUES ('ACME',1,1)"
        )


def test_invalid_filled_quantity_rejected(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM trader LIMIT 1")
        trader_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM instrument LIMIT 1")
        instrument_id = cur.fetchone()[0]
        with pytest.raises(CheckViolation):
            cur.execute(
                """INSERT INTO "order"
                   (trader_id,instrument_id,side,price_ticks,quantity,filled_quantity)
                   VALUES (%s,%s,'BUY',100,10,11)""",
                (trader_id, instrument_id),
            )


def test_order_history_no_auto_generated_id(db_conn):
    with db_conn.cursor() as cur:
        cur.execute(
            """SELECT column_default FROM information_schema.columns
               WHERE table_schema='public' AND table_name='order_history' AND column_name='id'"""
        )
        assert cur.fetchone()[0] is None


@pytest.mark.parametrize(
    ("trader_email", "status", "error"),
    [("missing@tradegraph.test", "FILLED", ForeignKeyViolation),
     ("alice@tradegraph.test", "OPEN", CheckViolation)],
)
def test_archive_integrity(db_conn, trader_email, status, error):
    with db_conn.cursor() as cur, pytest.raises(error):
        cur.execute(
            """INSERT INTO order_history
                   (id,trader_id,instrument_id,side,price_ticks,quantity,
                    filled_quantity,status,created_at,updated_at)
               SELECT -1, coalesce((SELECT t.id FROM trader t JOIN user_account u
                                    ON t.user_account_id=u.id WHERE u.email=%s),
                                   '00000000-0000-0000-0000-000000000000'::uuid),
                      id, 'BUY', 100, 1, 1, %s, now(), now()
               FROM instrument WHERE symbol='ACME'""",
            (trader_email, status),
        )


def test_position_composite_key(db_conn):
    with db_conn.cursor() as cur:
        cur.execute(
            """SELECT pg_get_constraintdef(oid) FROM pg_constraint
               WHERE conrelid='position'::regclass AND contype='p'"""
        )
        assert "(trader_id, instrument_id)" in cur.fetchone()[0]
