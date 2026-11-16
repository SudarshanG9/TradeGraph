"""Phase 1 wire/configuration contracts and independent proposed fee ledgers.

Financial examples specify the review proposal; they do not test SQL settlement,
which remains unimplemented until authorized Batch B.
"""

import json
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from random import Random
from uuid import UUID

import pytest

from backend.config import Settings
from backend.events.trade_event import BIGINT_MAX, TradeEvent
from backend.matching.order_book import Fill, Order, OrderBook

BUYER = UUID("00000000-0000-0000-0000-000000000001")
SELLER = UUID("00000000-0000-0000-0000-000000000002")
WHEN = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)


def event():
    return TradeEvent.from_fill(
        Fill(1, 101, 102, str(BUYER), str(SELLER), 100, 100),
        event_id=501, taker_order_id=102, occurred_at=WHEN,
    )


def test_actual_book_fill_to_immutable_event_and_json_round_trip():
    book = OrderBook()
    book.submit(Order(101, str(BUYER), 1, "BUY", 100, 100))
    result = book.submit(Order(102, str(SELLER), 1, "SELL", 99, 100))
    fill = result.fills[0]
    emitted = TradeEvent.from_fill(fill, event_id=501, taker_order_id=102, occurred_at=WHEN)
    assert emitted == event()
    assert emitted.price_ticks == 100  # maker price, not incoming SELL limit
    expected = {
        "event_id": 501, "instrument_id": 1, "buy_order_id": 101,
        "sell_order_id": 102, "buy_trader_id": str(BUYER),
        "sell_trader_id": str(SELLER), "price_ticks": 100, "quantity": 100,
        "taker_order_id": 102, "occurred_at": "2026-11-14T12:00:00Z",
    }
    assert emitted.to_dict() == expected
    assert json.loads(emitted.to_json()) == expected
    assert TradeEvent.from_json(emitted.to_json()) == emitted
    assert hash(TradeEvent.from_dict(expected)) == hash(emitted)
    with pytest.raises(FrozenInstanceError):
        emitted.quantity = 1


@pytest.mark.parametrize("name", [
    "event_id", "instrument_id", "buy_order_id", "sell_order_id",
    "price_ticks", "quantity", "taker_order_id",
])
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "100", BIGINT_MAX + 1])
def test_event_rejects_non_integer_or_out_of_range_fields(name, value):
    with pytest.raises(ValueError):
        replace(event(), **{name: value})


@pytest.mark.parametrize("change", [
    {"instrument_id": 2**31}, {"sell_order_id": 101}, {"taker_order_id": 999},
    {"sell_trader_id": BUYER}, {"buy_trader_id": str(BUYER)},
    {"occurred_at": datetime(2026, 11, 14)}, {"occurred_at": "2026-11-14"},
])
def test_event_rejects_invalid_identity_and_time(change):
    with pytest.raises(ValueError):
        replace(event(), **change)


def test_event_preserves_bigint_precision_and_normalizes_utc():
    local = datetime(2026, 11, 14, 17, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    value = replace(event(), event_id=BIGINT_MAX, quantity=BIGINT_MAX,
                    price_ticks=BIGINT_MAX, occurred_at=local)
    assert value.occurred_at == WHEN
    assert value.to_dict()["occurred_at"] == "2026-11-14T12:00:00Z"
    assert TradeEvent.from_json(value.to_json()) == value
    # Serialization produces independent data, not mutable event state.
    payload = value.to_dict()
    payload["quantity"] = 1
    assert value.quantity == BIGINT_MAX


@pytest.mark.parametrize("change", [
    {"extra": "unknown"}, {"quantity": None}, {"buy_trader_id": "not-a-uuid"},
    {"occurred_at": "2026-11-14T12:00:00"}, {"occurred_at": 123},
    {"buy_trader_id": BUYER},
])
def test_event_wire_validation(change):
    with pytest.raises(ValueError):
        TradeEvent.from_dict(event().to_dict() | change)


def test_event_missing_fields_and_non_object_json_rejected():
    payload = event().to_dict()
    del payload["event_id"]
    with pytest.raises(ValueError):
        TradeEvent.from_dict(payload)
    with pytest.raises(ValueError):
        TradeEvent.from_json("[]")


def configured_env():
    # Test-only values, never live credentials.
    return {
        "DATABASE_IDENTITY_MODE": "legacy",  # explicit pre-migration compatibility fixture
        "POSTGRES_RUNTIME_PASSWORD": "unit-runtime-password",
        "NEO4J_PASSWORD": "unit-graph-password",
        "JWT_SECRET": "unit-jwt-signing-key-with-32-or-more-characters",
    }


def test_native_configuration_defaults_secrets_and_identity_separation():
    values = configured_env() | {"POSTGRES_USER": "legacy_owner", "POSTGRES_PASSWORD": "owner-secret"}
    settings = Settings.from_env(values)
    assert (settings.postgres_host, settings.postgres_port, settings.postgres_db) == (
        "/tmp", 5432, "tradegraph")
    assert settings.postgres_runtime_user == "tradegraph_runtime"
    assert settings.postgres_runtime_password == values["POSTGRES_RUNTIME_PASSWORD"]
    assert settings.service_workers == 1 and settings.jwt_ttl_seconds == 900
    assert settings.health_timeout_seconds == 3 and settings.event_queue_capacity == 1024
    assert settings.neo4j_uri == "bolt://127.0.0.1:7687"
    for secret in (values["POSTGRES_RUNTIME_PASSWORD"], values["NEO4J_PASSWORD"], values["JWT_SECRET"]):
        assert secret not in repr(settings)
    with pytest.raises(FrozenInstanceError):
        settings.service_workers = 2


@pytest.mark.parametrize("name,value", [
    ("POSTGRES_RUNTIME_USER", "postgres"), ("POSTGRES_RUNTIME_USER", "tradegraph_owner"),
    ("POSTGRES_RUNTIME_USER", "trader_role"), ("POSTGRES_RUNTIME_USER", ""),
    ("SERVICE_WORKERS", "2"), ("JWT_ALGORITHM", "none"),
    ("JWT_TTL_SECONDS", "0"), ("JWT_TTL_SECONDS", "3601"),
    ("POSTGRES_PORT", "65536"), ("POSTGRES_PORT", "bad"),
    ("HEALTH_TIMEOUT_SECONDS", "0"), ("HEALTH_INTERVAL_SECONDS", "301"),
    ("EVENT_QUEUE_CAPACITY", "0"), ("POSTGRES_HOST", ""),
    ("REDIS_URL", "http://localhost:6379"), ("REDIS_URL", "redis://localhost:bad"),
    ("NEO4J_URI", "http://localhost:7474"),
    ("NEO4J_URI", "bolt://user:secret@localhost:7687"),
    ("JWT_SECRET", "short"), ("JWT_SECRET", " " * 40),
    ("NEO4J_PASSWORD", "replace_with_secure_password"),
    ("POSTGRES_RUNTIME_PASSWORD", ""),
])
def test_configuration_fails_closed(name, value):
    with pytest.raises(ValueError) as exc:
        Settings.from_env(configured_env() | {name: value})
    assert value not in str(exc.value) or value == ""


def test_configuration_requires_runtime_password_without_owner_fallback():
    values = configured_env()
    del values["POSTGRES_RUNTIME_PASSWORD"]
    with pytest.raises(ValueError, match="POSTGRES_RUNTIME_PASSWORD"):
        Settings.from_env(values | {"POSTGRES_PASSWORD": "owner-password"})
    with pytest.raises(ValueError, match="dedicated service login"):
        Settings.from_env(configured_env() | {
            "POSTGRES_ADMIN_USER": "native_admin", "POSTGRES_RUNTIME_USER": "native_admin"})


def test_process_environment_overrides_file_without_global_mutation(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    values = configured_env()
    path.write_text("\n".join(f"{k}={v}" for k, v in values.items()) +
                    "\nPOSTGRES_PORT=5433\nPOSTGRES_HOST=/native/socket\n")
    for key in (*values, "POSTGRES_HOST", "POSTGRES_RUNTIME_USER", "SERVICE_WORKERS", "POSTGRES_USER",
                "POSTGRES_ADMIN_USER", "NEO4J_URI", "NEO4J_USER", "JWT_ALGORITHM"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("POSTGRES_PORT", "5434")
    settings = Settings.from_env(env_file=path)
    assert settings.postgres_port == 5434
    assert settings.postgres_host == "/native/socket"
    import os
    assert "POSTGRES_RUNTIME_PASSWORD" not in os.environ
    assert Settings.from_env(values).postgres_port == 5432  # explicit mapping is isolated


def ceil_fraction(value):
    return -(-value.numerator // value.denominator)


def fee_ledger(side, fills, *, limit=100, quantity=100):
    """Independent exact model of the proposal, including terminal cancel.

    fills are (execution ticks, quantity, fee basis points as Fraction/int).
    The output is not a synthetic SQL/API result.
    """
    worst = Fraction(2, 10000)
    budget = lambda q: ceil_fraction(limit * q * worst)
    reserve = lambda q: limit * q + budget(q)
    cash, escrow, remaining, exact_fee = 20000 - reserve(quantity), reserve(quantity), quantity, Fraction(0)
    checkpoints = []
    for price, filled, bps in fills:
        before = remaining
        remaining -= filled
        value = price * filled
        release = reserve(before) - reserve(remaining)
        previous_assessed = ceil_fraction(exact_fee)
        exact_fee += Fraction(value) * bps / 10000
        if side == "BUY":
            charge = budget(before) - budget(remaining)
            cash += release - value - charge
        else:
            charge = ceil_fraction(exact_fee) - previous_assessed
            cash += release + value - charge
        escrow -= release
        assert min(cash, escrow) >= 0
        assert escrow == reserve(remaining)
        checkpoints.append((cash, escrow))
    # Terminal completion/cancel: release residual, finish BUY advance and refund.
    cash += reserve(remaining)
    escrow -= reserve(remaining)
    assessed = ceil_fraction(exact_fee)
    if side == "BUY":
        cash -= budget(remaining)
        assert budget(quantity) >= assessed
        cash += budget(quantity) - assessed
    assert min(cash, escrow) >= 0
    return cash, escrow, assessed, checkpoints


def test_rounding_counterexample_and_one_vs_100_fill_ledger():
    assert ceil_fraction(Fraction(10000 * 2, 10000)) == 2  # total reserve fee
    assert 100 * ceil_fraction(Fraction(100 * 2, 10000)) == 100  # naive tiny-fill fees
    for side, bps, expected_cash in (("BUY", 1, 9999), ("SELL", 2, 29998)):
        one = fee_ledger(side, [(100, 100, bps)])
        tiny = fee_ledger(side, [(100, 1, bps)] * 100)
        assert one[:3] == tiny[:3] == (expected_cash, 0, bps)
        assert tiny[3][49] == ((9998, 5001) if side == "BUY" else (19998, 5001))


def test_partial_cancel_no_fill_cancel_and_seller_improved_price():
    assert fee_ledger("BUY", [(100, 50, 1)])[:3] == (14999, 0, 1)
    assert fee_ledger("SELL", [(100, 50, 2)])[:3] == (24999, 0, 1)
    assert fee_ledger("BUY", [(100, 1, 1)])[:3] == (19899, 0, 1)
    assert fee_ledger("SELL", [(100, 1, 2)])[:3] == (20099, 0, 1)
    assert fee_ledger("BUY", [])[:3] == (20000, 0, 0)
    assert fee_ledger("SELL", [])[:3] == (20000, 0, 0)
    # Seller fees can exceed its limit-price fee reserve and are funded by proceeds.
    assert fee_ledger("SELL", [(105, 100, 2)])[:3] == (30497, 0, 3)


def test_partitioned_fee_budget_price_improvement_and_mixed_roles():
    rng = Random(20261114)
    for _ in range(100):
        remaining = 100
        buy_fills, sell_fills = [], []
        while remaining:
            amount = rng.randint(1, remaining)
            remaining -= amount
            rate = rng.choice((Fraction(1, 2), Fraction(1), Fraction(2)))
            buy_fills.append((rng.randint(1, 105), amount, rate))
            sell_fills.append((rng.randint(100, 10000), amount, rate))
        buyer = fee_ledger("BUY", buy_fills, limit=105)
        seller = fee_ledger("SELL", sell_fills)
        assert buyer[0] == 20000 - sum(p * q for p, q, _ in buy_fills) - buyer[2]
        assert seller[0] == 20000 + sum(p * q for p, q, _ in sell_fills) - seller[2]
    # Exact calculation retains a fractional fee far beyond float precision.
    value = 500_000_000_000_000_001
    assert ceil_fraction(Fraction(value * 2, 10000)) == 100_000_000_000_001


def test_isolated_database_credentials_require_distinct_services_and_private_trader_provider():
    values=configured_env()|{'DATABASE_IDENTITY_MODE':'isolated','POSTGRES_AUTH_USER':'test_auth',
        'POSTGRES_AUTH_PASSWORD':'test-auth-secret-with-length','POSTGRES_COMPLIANCE_USER':'test_compliance',
        'POSTGRES_COMPLIANCE_PASSWORD':'test-compliance-secret-with-length','TRADER_DATABASE_CREDENTIALS_FILE':'/private/manifest.json'}
    settings=Settings.from_env(values)
    assert settings.database_identity_mode=='isolated'
    assert values['POSTGRES_AUTH_PASSWORD'] not in repr(settings)
    for extra in ({'POSTGRES_AUTH_USER':'tradegraph_runtime'},{'TRADER_DATABASE_CREDENTIALS_FILE':''},
                  {'POSTGRES_COMPLIANCE_PASSWORD':''},{'DATABASE_IDENTITY_MODE':'unknown'}):
        with pytest.raises(ValueError):Settings.from_env(values|extra)


def test_database_identity_default_is_secure_without_implicit_legacy_fallback():
    values=configured_env();values.pop('DATABASE_IDENTITY_MODE')
    with pytest.raises(ValueError,match='Isolated identity'):
        Settings.from_env(values)
