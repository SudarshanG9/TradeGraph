-- Backward-compatible routine replacement; do not run the full installer.
BEGIN;
-- Terminal processing is idempotent and shares account-before-order locking.
CREATE OR REPLACE FUNCTION public.cancel_order(p_order bigint,p_trader uuid) RETURNS bigint
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE o public."order"%ROWTYPE; q numeric; tick integer; rate numeric; fee0 numeric; feeq numeric; release numeric; credit numeric; actual_order_fee numeric;
BEGIN
 PERFORM trader_id FROM public.margin_account WHERE trader_id=p_trader FOR UPDATE;
 SELECT * INTO o FROM public."order" WHERE id=p_order AND trader_id=p_trader FOR UPDATE;
 IF o.id IS NULL THEN
   IF EXISTS(SELECT 1 FROM public.order_history WHERE id=p_order AND trader_id=p_trader AND status='CANCELLED') THEN RETURN 0; END IF;
   RAISE EXCEPTION 'Unknown owned order' USING ERRCODE='22023';
 END IF;
 IF o.status='CANCELLED' THEN RETURN 0; END IF;
 IF o.status='FILLED' THEN RAISE EXCEPTION 'Filled order cannot be canceled' USING ERRCODE='22023'; END IF;
 q:=o.quantity::numeric-o.filled_quantity;
 SELECT i.tick_size,greatest(f.maker_fee_bps,f.taker_fee_bps)*0.0001 INTO tick,rate
 FROM public.instrument i CROSS JOIN public.margin_account m JOIN public.fee_tier f ON f.id=m.fee_tier_id
 WHERE i.id=o.instrument_id AND m.trader_id=p_trader;
 fee0:=ceil(o.price_ticks::numeric*tick*o.quantity*rate);
 feeq:=ceil(o.price_ticks::numeric*tick*q*rate);
 release:=o.price_ticks::numeric*tick*q+feeq;
 credit:=release;
 IF o.side='BUY' THEN
   actual_order_fee:=public.order_fee(p_order);
   credit:=release-feeq+fee0-actual_order_fee;
   IF fee0<actual_order_fee THEN RAISE EXCEPTION 'BUY fee exceeds budget' USING ERRCODE='22023'; END IF;
 END IF;
 UPDATE public.margin_account SET cash_balance=(cash_balance::numeric+credit)::bigint,
   escrow_balance=(escrow_balance::numeric-release)::bigint,updated_at=now() WHERE trader_id=p_trader;
 UPDATE public."order" SET status='CANCELLED',updated_at=now() WHERE id=p_order;
 RETURN q::bigint;
END $$;
REVOKE ALL ON FUNCTION public.cancel_order(bigint,uuid) FROM PUBLIC,trader_role,compliance_admin_role;

COMMIT;
