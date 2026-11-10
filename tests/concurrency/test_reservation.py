import uuid
from concurrent.futures import ThreadPoolExecutor
from secrets import token_hex
from threading import Barrier

import bcrypt
import pytest
from psycopg.errors import InvalidParameterValue, NumericValueOutOfRange, RaiseException

from scripts.verify_schema import db_connect

pytestmark = pytest.mark.day2


@pytest.fixture
def temporary_trader():
    token = uuid.uuid4().hex
    email = f"day2-{token}@tradegraph.test"
    hashed = bcrypt.hashpw(token_hex(24).encode(), bcrypt.gensalt()).decode()
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM fee_tier WHERE tier_name = 'STANDARD'")
            tier = cur.fetchone()
            assert tier is not None, "Missing STANDARD reference fee tier"
            tier_id = tier[0]
            cur.execute(
                "INSERT INTO user_account(email, password_hash, role) "
                "VALUES (%s, %s, 'TRADER') RETURNING id",
                (email, hashed),
            )
            user_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO trader(user_account_id, full_name) "
                "VALUES (%s, 'Day 2 Test Trader') RETURNING id",
                (user_id,),
            )
            trader_id = cur.fetchone()[0]
            cur.execute(
                "INSERT INTO margin_account(trader_id,cash_balance,fee_tier_id) "
                "VALUES (%s, 100000, %s)",
                (trader_id, tier_id),
            )
    try:
        yield trader_id
    finally:
        with db_connect() as conn:
            with conn.cursor() as cur:
                # Delete only records belonging to this fresh test fixture.
                cur.execute('DELETE FROM "order" WHERE trader_id=%s', (trader_id,))
                cur.execute("DELETE FROM margin_account WHERE trader_id=%s", (trader_id,))
                cur.execute("DELETE FROM trader WHERE id=%s", (trader_id,))
                cur.execute("DELETE FROM user_account WHERE id=%s", (user_id,))


def acme_id():
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM instrument WHERE symbol='ACME'")
            row = cur.fetchone()
            assert row is not None
            return row[0]


def account_state(trader_id):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT cash_balance,escrow_balance FROM margin_account "
                "WHERE trader_id=%s", (trader_id,)
            )
            return cur.fetchone()


def order_count(trader_id):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM "order" WHERE trader_id=%s', (trader_id,))
            return cur.fetchone()[0]


def reserve_once(trader_id, instrument_id, barrier, price_ticks):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = '10s'")
            barrier.wait(timeout=10)
            try:
                cur.execute(
                    "SELECT public.place_and_reserve_order(%s,%s,'BUY',%s,1)",
                    (trader_id, instrument_id, price_ticks),
                )
                return ("accepted", cur.fetchone()[0])
            except RaiseException as exc:
                if exc.diag.message_primary != "Insufficient available funds":
                    raise
                conn.rollback()
                return ("rejected", None)


def test_two_concurrent_orders_cannot_double_spend(temporary_trader):
    trader = temporary_trader
    assert account_state(trader) == (100000, 0)
    instrument_id = acme_id()
    barrier = Barrier(2)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(reserve_once, trader, instrument_id, barrier, 60000)
            for _ in range(2)
        ]
        outcomes = [f.result(timeout=20) for f in futures]
    assert sorted(x[0] for x in outcomes) == ["accepted", "rejected"]
    # At 2 bps, 60,000 + CEIL(12) = 60,012, leaving 39,988.
    assert account_state(trader) == (39988, 60012)
    assert order_count(trader) == 1


def test_repeated_concurrent_race_with_eight_workers(temporary_trader):
    trader = temporary_trader
    barrier = Barrier(8)
    instrument_id = acme_id()
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [
            pool.submit(reserve_once, trader, instrument_id, barrier, 25000)
            for _ in range(8)
        ]
        outcomes = [f.result(timeout=20) for f in futures]
    # Each order reserves 25,005, so only three can fit into 100,000.
    assert sum(outcome[0] == "accepted" for outcome in outcomes) == 3
    assert account_state(trader) == (24985, 75015)
    assert order_count(trader) == 3


def test_explicit_transaction_rollback_reverts_cash_and_order(temporary_trader):
    trader = temporary_trader
    before = account_state(trader)
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT public.place_and_reserve_order(%s,%s,'BUY',1000,10)",
                (trader, acme_id()),
            )
            order_id = cur.fetchone()[0]
            cur.execute('SELECT status, filled_quantity FROM "order" WHERE id=%s', (order_id,))
            assert cur.fetchone() == ("OPEN", 0)
            cur.execute(
                "SELECT cash_balance, escrow_balance FROM margin_account WHERE trader_id=%s",
                (trader,),
            )
            assert cur.fetchone() == (89998, 10002)
            # Explicitly undo an otherwise valid reservation transaction.
            conn.rollback()
    assert account_state(trader) == before
    assert order_count(trader) == 0


@pytest.mark.parametrize("side, price_ticks, quantity, error, message", [
    (None, 100, 1, InvalidParameterValue, "Missing required order field"),
    ("HOLD", 100, 1, InvalidParameterValue, "Invalid order side"),
    ("BUY", 0, 1, InvalidParameterValue, "must be positive"),
    ("BUY", 100, 0, InvalidParameterValue, "must be positive"),
    ("BUY", -100, 1, InvalidParameterValue, "must be positive"),
    ("SELL", 100, -1, InvalidParameterValue, "must be positive"),
    ("BUY", 200000, 1, RaiseException, "Insufficient available funds"),
])
def test_invalid_order_is_rejected_without_balance_change(
    temporary_trader, side, price_ticks, quantity, error, message
):
    trader = temporary_trader
    before = account_state(trader)
    with pytest.raises(error, match=message):
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT public.place_and_reserve_order(%s,%s,%s,%s,%s)",
                    (trader, acme_id(), side, price_ticks, quantity),
                )
    assert account_state(trader) == before
    assert order_count(trader) == 0


def test_instrument_lot_size_is_enforced(temporary_trader):
    trader = temporary_trader
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM instrument WHERE symbol='BETA'")
            beta_id = cur.fetchone()[0]
    with pytest.raises(InvalidParameterValue, match="lot size"):
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT public.place_and_reserve_order(%s,%s,'BUY',100,3)",
                    (trader, beta_id),
                )
    assert account_state(trader) == (100000, 0)
    assert order_count(trader) == 0


def test_reservation_uses_instrument_tick_size(temporary_trader):
    with db_connect() as conn:
        beta_id = conn.execute("SELECT id FROM instrument WHERE symbol='BETA'").fetchone()[0]
        conn.execute(
            "SELECT public.place_and_reserve_order(%s,%s,'BUY',100,10)",
            (temporary_trader, beta_id),
        )
    # 100 ticks × 5 minor units × 10 units = 5,000, plus a 1-unit fee.
    assert account_state(temporary_trader) == (94999, 5001)


def test_buy_and_sell_both_reserve_collateral(temporary_trader):
    trader = temporary_trader
    instrument_id = acme_id()
    with db_connect() as conn:
        with conn.cursor() as cur:
            for side in ("BUY", "SELL"):
                cur.execute(
                    "SELECT public.place_and_reserve_order(%s,%s,%s,1000,10)",
                    (trader, instrument_id, side),
                )
                assert cur.fetchone()[0] > 0
    assert account_state(trader) == (79996, 20004)
    assert order_count(trader) == 2


def test_unknown_instrument_is_rejected(temporary_trader):
    trader = temporary_trader
    with pytest.raises(InvalidParameterValue, match="Unknown instrument"):
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT public.place_and_reserve_order(%s,-999,'BUY',100,1)",
                    (trader,),
                )
    assert account_state(trader) == (100000, 0)
    assert order_count(trader) == 0


def test_missing_trader_margin_is_rejected(temporary_trader):
    with pytest.raises(InvalidParameterValue, match="margin account"):
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT public.place_and_reserve_order(%s,%s,'BUY',100,1)",
                    (uuid.uuid4(), acme_id()),
                )
    assert account_state(temporary_trader) == (100000, 0)


def test_inactive_instrument_is_rejected(temporary_trader):
    unique_symbol = "D2OFF" + uuid.uuid4().hex[:10]
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO instrument(symbol,tick_size,lot_size,is_active) "
                "VALUES (%s,1,1,FALSE) RETURNING id",
                (unique_symbol,),
            )
            inactive_id = cur.fetchone()[0]
    try:
        with pytest.raises(InvalidParameterValue, match="inactive"):
            with db_connect() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT public.place_and_reserve_order(%s,%s,'BUY',100,1)",
                        (temporary_trader, inactive_id),
                    )
        assert account_state(temporary_trader) == (100000, 0)
    finally:
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM instrument WHERE id=%s", (inactive_id,))


def test_reservation_rejects_bigint_overflow(temporary_trader):
    with pytest.raises(NumericValueOutOfRange, match="BIGINT"):
        with db_connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT public.place_and_reserve_order(%s,%s,'BUY',%s,%s)",
                    (temporary_trader, acme_id(), 2**63 - 1, 2**63 - 1),
                )
    assert account_state(temporary_trader) == (100000, 0)
    assert order_count(temporary_trader) == 0


def test_fractional_fee_rounds_up_at_large_notional(temporary_trader):
    price_ticks = 500_000_000_000_000_001
    expected = price_ticks + 100_000_000_000_001
    with db_connect() as conn:
        conn.execute(
            "UPDATE margin_account SET cash_balance=%s WHERE trader_id=%s",
            (expected, temporary_trader),
        )
        conn.execute(
            "SELECT public.place_and_reserve_order(%s,%s,'BUY',%s,1)",
            (temporary_trader, acme_id(), price_ticks),
        )
    assert account_state(temporary_trader) == (0, expected)
    assert order_count(temporary_trader) == 1


@pytest.mark.parametrize("role", ["trader_role", "compliance_admin_role"])
def test_generic_roles_cannot_execute_unbound_definer_function(role):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT has_function_privilege(%s, "
                "'public.place_and_reserve_order(uuid,integer,text,bigint,bigint)', "
                "'EXECUTE')",
                (role,),
            )
            assert cur.fetchone()[0] is False
