-- =============================================================
-- seed_users.sql  –  demo accounts, traders, KYC, margin, desk
-- =============================================================

-- ── 1. USER ACCOUNTS (bcrypt via pgcrypto) ───────────────────
INSERT INTO user_account (email, password_hash, role)
VALUES
    ('alice@tradegraph.test',
     crypt('password123', gen_salt('bf', 10)),
     'TRADER'),
    ('bob@tradegraph.test',
     crypt('password123', gen_salt('bf', 10)),
     'TRADER'),
    ('carol@tradegraph.test',
     crypt('password123', gen_salt('bf', 10)),
     'TRADER'),
    ('admin@tradegraph.test',
     crypt('password123', gen_salt('bf', 10)),
     'COMPLIANCE_ADMIN')
ON CONFLICT (email) DO NOTHING;

-- ── 2. TRADERS ───────────────────────────────────────────────
INSERT INTO trader (user_account_id, desk_id, full_name)
SELECT u.id,
       d.id,
       v.full_name
FROM (VALUES
    ('alice@tradegraph.test', 'Alice'),
    ('bob@tradegraph.test',   'Bob'),
    ('carol@tradegraph.test', 'Carol')
) AS v(email, full_name)
JOIN user_account u ON u.email = v.email
JOIN desk         d ON d.name  = 'Equities'
ON CONFLICT (user_account_id) DO NOTHING;

-- ── 3. DESK MANAGER  (Alice manages Equities) ────────────────
UPDATE desk
SET manager_trader_id = (
    SELECT t.id
    FROM trader t
    JOIN user_account u ON u.id = t.user_account_id
    WHERE u.email = 'alice@tradegraph.test'
)
WHERE name = 'Equities'
  AND manager_trader_id IS NULL;

-- ── 4. KYC PROFILES ──────────────────────────────────────────
INSERT INTO kyc_profile (trader_id, pan_hash, verified, verified_at)
SELECT t.id,
       encode(digest(v.pan, 'sha256'), 'hex'),
       true,
       now()
FROM (VALUES
    ('alice@tradegraph.test', 'AABPA1234C'),
    ('bob@tradegraph.test',   'BBCPB5678D'),
    ('carol@tradegraph.test', 'CCDPC9012E')
) AS v(email, pan)
JOIN user_account u ON u.email = v.email
JOIN trader       t ON t.user_account_id = u.id
ON CONFLICT (trader_id) DO NOTHING;

-- ── 5. MARGIN ACCOUNTS ───────────────────────────────────────
INSERT INTO margin_account (trader_id, cash_balance, escrow_balance, fee_tier_id)
SELECT t.id,
       1000000,   -- $10,000.00 in cents
       0,
       f.id
FROM user_account u
JOIN trader      t ON t.user_account_id = u.id
JOIN fee_tier    f ON f.tier_name = 'STANDARD'
WHERE u.email IN (
    'alice@tradegraph.test',
    'bob@tradegraph.test',
    'carol@tradegraph.test'
)
ON CONFLICT (trader_id) DO NOTHING;
