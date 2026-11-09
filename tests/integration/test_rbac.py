import pytest
from psycopg.errors import DataException, InsufficientPrivilege

pytestmark = pytest.mark.day1


def test_trader_no_direct_disclosure_access_even_if_app_role_spoofed(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE trader_role")
        cur.execute("SET LOCAL app.role = 'COMPLIANCE_ADMIN'")
        with pytest.raises(InsufficientPrivilege):
            cur.execute("SELECT * FROM market_disclosure")


def test_trader_cannot_update_margin_account(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE trader_role")
        with pytest.raises(InsufficientPrivilege):
            cur.execute("UPDATE margin_account SET cash_balance=0")


def test_admin_policy_and_generated_full_text(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE compliance_admin_role")
        cur.execute("SET LOCAL app.role = 'COMPLIANCE_ADMIN'")
        cur.execute(
            """INSERT INTO market_disclosure(title,body)
               VALUES ('Test merger', 'A fictional merger notice') RETURNING id"""
        )
        disclosure_id = cur.fetchone()[0]
        cur.execute(
            """SELECT body_tsv @@ plainto_tsquery('english','merger')
               FROM market_disclosure WHERE id=%s""",
            (disclosure_id,),
        )
        assert cur.fetchone()[0] is True
        cur.execute("SET LOCAL app.role = 'TRADER'")
        cur.execute("SELECT id FROM market_disclosure WHERE id=%s", (disclosure_id,))
        assert cur.fetchone() is None  # RLS hides the row even though role has SELECT


def test_admin_insert_blocked_without_admin_context(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE compliance_admin_role")
        cur.execute("SET LOCAL app.role = 'TRADER'")
        with pytest.raises(InsufficientPrivilege):
            cur.execute(
                """INSERT INTO market_disclosure(title,body)
                   VALUES ('blocked','must not persist')"""
            )


def test_vector_dimensions_and_cosine_operator(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE compliance_admin_role")
        cur.execute("SET LOCAL app.role = 'COMPLIANCE_ADMIN'")
        # Synthetic, not an actual trading regime; insert is rolled back by fixture.
        cur.execute("SELECT id FROM instrument WHERE symbol='ACME'")
        instrument_id = cur.fetchone()[0]
        feature_text = '[0.01,0.2,0.03,0.04,0.05,0.06]'
        cur.execute(
            """INSERT INTO regime_snapshot(instrument_id,captured_at,features)
               VALUES (%s, now(), %s::vector) RETURNING id""",
            (instrument_id, feature_text),
        )
        snapshot_id = cur.fetchone()[0]
        cur.execute(
            """SELECT vector_dims(features),
                      features <=> %s::vector AS cosine_distance
               FROM regime_snapshot WHERE id=%s""",
            (feature_text, snapshot_id),
        )
        dimensions, distance = cur.fetchone()
        assert dimensions == 6
        assert distance == pytest.approx(0, abs=1e-6)
        cur.execute("SET LOCAL app.role = 'TRADER'")
        cur.execute("SELECT id FROM regime_snapshot WHERE id=%s", (snapshot_id,))
        assert cur.fetchone() is None


def test_snapshot_rejects_wrong_vector_dimensions(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SET LOCAL ROLE compliance_admin_role")
        cur.execute("SET LOCAL app.role = 'COMPLIANCE_ADMIN'")
        with pytest.raises(DataException, match="expected 6 dimensions, not 2"):
            cur.execute(
                """INSERT INTO regime_snapshot(instrument_id,captured_at,features)
                   SELECT id, now(), '[1,2]'::vector FROM instrument WHERE symbol='ACME'"""
            )
