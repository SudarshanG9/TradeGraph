DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'trader_role') THEN
        CREATE ROLE trader_role NOLOGIN;
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'compliance_admin_role') THEN
        CREATE ROLE compliance_admin_role NOLOGIN;
    END IF;
END $$;

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;



-- 1. USER ACCOUNTS
CREATE TABLE user_account (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) NOT NULL
        CHECK (role IN ('TRADER', 'COMPLIANCE_ADMIN')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. DESKS
CREATE TABLE desk (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) UNIQUE NOT NULL,
    parent_desk_id INT REFERENCES desk(id)
        ON DELETE SET NULL,
    CHECK (parent_desk_id IS NULL OR parent_desk_id <> id)
);

-- 3. TRADERS
CREATE TABLE trader (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_account_id UUID UNIQUE NOT NULL
        REFERENCES user_account(id),
    desk_id INT REFERENCES desk(id),
    full_name VARCHAR(150) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ALTER TABLE: completes the desk-manager relationship
ALTER TABLE desk
ADD COLUMN manager_trader_id UUID REFERENCES trader(id);

-- 4. KYC
CREATE TABLE kyc_profile (
    trader_id UUID PRIMARY KEY
        REFERENCES trader(id) ON DELETE CASCADE,
    pan_hash VARCHAR(128) NOT NULL,
    verified BOOLEAN NOT NULL DEFAULT false,
    verified_at TIMESTAMPTZ,
    CONSTRAINT verified_has_timestamp CHECK (NOT verified OR verified_at IS NOT NULL)
);

-- 5. FEE TIERS
CREATE TABLE fee_tier (
    id SERIAL PRIMARY KEY,
    tier_name VARCHAR(50) UNIQUE NOT NULL,
    maker_fee_bps NUMERIC(6,3) NOT NULL
        CHECK (maker_fee_bps >= 0),
    taker_fee_bps NUMERIC(6,3) NOT NULL
        CHECK (taker_fee_bps >= 0)
);

-- 6. MARGIN ACCOUNTS
CREATE TABLE margin_account (
    trader_id UUID PRIMARY KEY
        REFERENCES trader(id) ON DELETE CASCADE,
    cash_balance BIGINT NOT NULL
        CHECK (cash_balance >= 0),
    escrow_balance BIGINT NOT NULL DEFAULT 0
        CHECK (escrow_balance >= 0),
    fee_tier_id INT NOT NULL REFERENCES fee_tier(id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 7. INSTRUMENTS
CREATE TABLE instrument (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(20) UNIQUE NOT NULL,
    tick_size INT NOT NULL CHECK (tick_size > 0),
    lot_size INT NOT NULL CHECK (lot_size > 0),
    is_active BOOLEAN NOT NULL DEFAULT true
);

-- 8. ACTIVE ORDERS
CREATE TABLE "order" (
    id BIGSERIAL PRIMARY KEY,
    trader_id UUID NOT NULL REFERENCES trader(id),
    instrument_id INT NOT NULL REFERENCES instrument(id),
    side VARCHAR(4) NOT NULL
        CHECK (side IN ('BUY', 'SELL')),
    price_ticks BIGINT NOT NULL CHECK (price_ticks > 0),
    quantity BIGINT NOT NULL CHECK (quantity > 0),
    filled_quantity BIGINT NOT NULL DEFAULT 0
        CHECK (filled_quantity >= 0),
    status VARCHAR(12) NOT NULL DEFAULT 'OPEN'
        CHECK (status IN (
            'OPEN', 'PARTIAL', 'FILLED', 'CANCELLED'
        )),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (filled_quantity <= quantity)
);

CREATE INDEX idx_order_instrument_side_price
ON "order"(instrument_id, side, price_ticks, created_at, id)
WHERE status IN ('OPEN', 'PARTIAL');
CREATE INDEX idx_order_trader_time ON "order"(trader_id, created_at DESC);

-- 9. ORDER ARCHIVE
CREATE TABLE order_history (
    id BIGINT PRIMARY KEY,
    trader_id UUID NOT NULL REFERENCES trader(id),
    instrument_id INT NOT NULL REFERENCES instrument(id),
    side VARCHAR(4) NOT NULL CHECK (side IN ('BUY', 'SELL')),
    price_ticks BIGINT NOT NULL CHECK (price_ticks > 0),
    quantity BIGINT NOT NULL CHECK (quantity > 0),
    filled_quantity BIGINT NOT NULL CHECK (filled_quantity >= 0),
    status VARCHAR(12) NOT NULL CHECK (status IN ('FILLED', 'CANCELLED')),
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    CHECK (filled_quantity <= quantity),
    archived_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_order_history_trader_time ON order_history(trader_id, archived_at DESC);

-- 10. EXECUTIONS
CREATE TABLE execution (
    id BIGSERIAL PRIMARY KEY,
    instrument_id INT NOT NULL REFERENCES instrument(id),
    buy_order_id BIGINT NOT NULL,
    sell_order_id BIGINT NOT NULL,
    buy_trader_id UUID NOT NULL REFERENCES trader(id),
    sell_trader_id UUID NOT NULL REFERENCES trader(id),
    price_ticks BIGINT NOT NULL CHECK (price_ticks > 0),
    quantity BIGINT NOT NULL CHECK (quantity > 0),
    executed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (buy_trader_id <> sell_trader_id),
    CHECK (buy_order_id <> sell_order_id)
);

CREATE INDEX idx_execution_instrument_time
ON execution(instrument_id, executed_at DESC);
CREATE INDEX idx_execution_buy_trader ON execution(buy_trader_id);
CREATE INDEX idx_execution_sell_trader ON execution(sell_trader_id);

-- 11. POSITIONS
CREATE TABLE position (
    trader_id UUID NOT NULL REFERENCES trader(id),
    instrument_id INT NOT NULL REFERENCES instrument(id),
    net_quantity BIGINT NOT NULL DEFAULT 0,
    realized_pnl BIGINT NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (trader_id, instrument_id)
);

-- 12. MARKET DISCLOSURES
CREATE TABLE market_disclosure (
    id BIGSERIAL PRIMARY KEY,
    instrument_id INT REFERENCES instrument(id),
    title VARCHAR(300) NOT NULL,
    body TEXT NOT NULL,
    body_tsv TSVECTOR GENERATED ALWAYS AS (
        to_tsvector(
            'english'::regconfig,
            coalesce(title, '') || ' ' ||
            coalesce(body, '')
        )
    ) STORED,
    published_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_disclosure_tsv
ON market_disclosure USING GIN(body_tsv);

-- 13. MARKET REGIME SNAPSHOTS
CREATE TABLE regime_snapshot (
    id BIGSERIAL PRIMARY KEY,
    instrument_id INT NOT NULL REFERENCES instrument(id),
    captured_at TIMESTAMPTZ NOT NULL,
    features VECTOR(6) NOT NULL,
    UNIQUE (instrument_id, captured_at)
);

CREATE INDEX idx_regime_hnsw
ON regime_snapshot
USING hnsw (features vector_cosine_ops);

-- Explicit DROP demonstration
CREATE TABLE _scratch_migration_test (id INT);
DROP TABLE _scratch_migration_test;



-- Database-level roles and baseline privileges
GRANT USAGE ON SCHEMA public
TO trader_role, compliance_admin_role;

GRANT SELECT ON desk, fee_tier, instrument TO trader_role;

GRANT SELECT ON
    desk, trader, fee_tier, instrument,
    "order", order_history, execution,
    position, margin_account
TO compliance_admin_role;

REVOKE ALL ON market_disclosure, regime_snapshot
FROM PUBLIC, trader_role;

GRANT SELECT, INSERT, UPDATE, DELETE
ON market_disclosure, regime_snapshot
TO compliance_admin_role;

GRANT USAGE ON SEQUENCE
    market_disclosure_id_seq,
    regime_snapshot_id_seq
TO compliance_admin_role;

-- Row-level security
ALTER TABLE market_disclosure ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_disclosure FORCE ROW LEVEL SECURITY;

CREATE POLICY disclosure_admin_only
ON market_disclosure
TO compliance_admin_role
USING (
    current_setting('app.role', true) = 'COMPLIANCE_ADMIN'
)
WITH CHECK (
    current_setting('app.role', true) = 'COMPLIANCE_ADMIN'
);

ALTER TABLE regime_snapshot ENABLE ROW LEVEL SECURITY;
ALTER TABLE regime_snapshot FORCE ROW LEVEL SECURITY;

CREATE POLICY regime_admin_only
ON regime_snapshot
TO compliance_admin_role
USING (
    current_setting('app.role', true) = 'COMPLIANCE_ADMIN'
)
WITH CHECK (
    current_setting('app.role', true) = 'COMPLIANCE_ADMIN'
);
