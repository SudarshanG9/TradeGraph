BEGIN;

CREATE FUNCTION public.place_and_reserve_order(
    p_trader_id UUID,
    p_instrument_id INTEGER,
    p_side TEXT,
    p_price_ticks BIGINT,
    p_quantity BIGINT
)
RETURNS BIGINT
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
    v_tick_size INTEGER;
    v_lot_size INTEGER;
    v_active BOOLEAN;
    v_cash BIGINT;
    v_escrow BIGINT;
    v_fee_bps NUMERIC;
    v_notional NUMERIC;
    v_fee NUMERIC;
    v_required NUMERIC;
    v_order_id BIGINT;
    v_bigint_max CONSTANT NUMERIC := 9223372036854775807;
BEGIN
    -- Validate before acquiring money locks.
    IF p_trader_id IS NULL OR p_instrument_id IS NULL
       OR p_side IS NULL OR p_price_ticks IS NULL
       OR p_quantity IS NULL THEN
        RAISE EXCEPTION 'Missing required order field' USING ERRCODE = '22023';
    END IF;

    IF p_side NOT IN ('BUY', 'SELL') THEN
        RAISE EXCEPTION 'Invalid order side' USING ERRCODE = '22023';
    END IF;

    IF p_price_ticks <= 0 OR p_quantity <= 0 THEN
        RAISE EXCEPTION 'Price and quantity must be positive' USING ERRCODE = '22023';
    END IF;

    SELECT tick_size, lot_size, is_active
      INTO v_tick_size, v_lot_size, v_active
    FROM public.instrument
    WHERE id = p_instrument_id
    FOR SHARE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Unknown instrument' USING ERRCODE = '22023';
    END IF;
    IF NOT v_active THEN
        RAISE EXCEPTION 'Instrument is inactive' USING ERRCODE = '22023';
    END IF;
    IF MOD(p_quantity, v_lot_size) <> 0 THEN
        RAISE EXCEPTION 'Quantity violates instrument lot size' USING ERRCODE = '22023';
    END IF;

    -- The locked row is the *single* reservation serialization point.
    SELECT ma.cash_balance, ma.escrow_balance,
           GREATEST(ft.maker_fee_bps, ft.taker_fee_bps)
      INTO v_cash, v_escrow, v_fee_bps
    FROM public.margin_account AS ma
    JOIN public.fee_tier AS ft ON ft.id = ma.fee_tier_id
    JOIN public.trader AS t ON t.id = ma.trader_id
    JOIN public.user_account AS ua ON ua.id = t.user_account_id
    WHERE ma.trader_id = p_trader_id
      AND ua.role = 'TRADER'
    FOR UPDATE OF ma;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Trader margin account not found' USING ERRCODE = '22023';
    END IF;

    -- NUMERIC intermediate arithmetic avoids BIGINT multiplication overflow.
    v_notional := p_price_ticks::NUMERIC * v_tick_size::NUMERIC * p_quantity::NUMERIC;
    -- Multiply by the exact basis-point factor so division scale cannot round away a fractional fee.
    v_fee := CEIL(v_notional * v_fee_bps * 0.0001);
    v_required := v_notional + v_fee;

    IF v_required > v_bigint_max
       OR v_required + v_escrow::NUMERIC > v_bigint_max THEN
        RAISE EXCEPTION 'Reservation exceeds BIGINT range' USING ERRCODE = '22003';
    END IF;

    IF v_cash::NUMERIC < v_required THEN
        RAISE EXCEPTION 'Insufficient available funds' USING ERRCODE = 'P0001';
    END IF;

    UPDATE public.margin_account
       SET cash_balance = cash_balance - v_required::BIGINT,
           escrow_balance = escrow_balance + v_required::BIGINT,
           updated_at = NOW()
     WHERE trader_id = p_trader_id;

    INSERT INTO public."order" (
        trader_id, instrument_id, side, price_ticks,
        quantity, filled_quantity, status
    ) VALUES (
        p_trader_id, p_instrument_id, p_side,
        p_price_ticks, p_quantity, 0, 'OPEN'
    ) RETURNING id INTO v_order_id;

    RETURN v_order_id;
END;
$$;

-- Do not expose an unbound caller-supplied trader identity to generic roles.
REVOKE ALL ON FUNCTION public.place_and_reserve_order(
    UUID, INTEGER, TEXT, BIGINT, BIGINT
) FROM PUBLIC, trader_role, compliance_admin_role;

COMMIT;
