
INSERT INTO fee_tier
(tier_name, maker_fee_bps, taker_fee_bps)
VALUES
('STANDARD', 1.000, 2.000),
('VIP', 0.500, 1.000)
ON CONFLICT (tier_name) DO NOTHING;

INSERT INTO instrument
(symbol, tick_size, lot_size)
VALUES
('ACME', 1, 1),
('BETA', 5, 10),
('GAMMA', 10, 5)
ON CONFLICT (symbol) DO NOTHING;

INSERT INTO desk(name)
VALUES ('Global Trading')
ON CONFLICT (name) DO NOTHING;

INSERT INTO desk(name, parent_desk_id)
SELECT 'Equities', id
FROM desk
WHERE name = 'Global Trading'
ON CONFLICT (name) DO NOTHING;
