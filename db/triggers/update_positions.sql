-- Exact rational weighted-average cost recomputation; no cost-basis column.
CREATE OR REPLACE FUNCTION public.recompute_position() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE who uuid; r record; q numeric; delta numeric; px numeric; closed numeric;
        an numeric; ad numeric; pn numeric; pd numeric; change_n numeric; g numeric;
BEGIN
  FOREACH who IN ARRAY ARRAY[NEW.buy_trader_id,NEW.sell_trader_id] LOOP
    q:=0; an:=0; ad:=1; pn:=0; pd:=1;
    FOR r IN SELECT e.*,i.tick_size FROM public.execution e JOIN public.instrument i ON i.id=e.instrument_id
             WHERE e.instrument_id=NEW.instrument_id AND (e.buy_trader_id=who OR e.sell_trader_id=who) ORDER BY e.id LOOP
      delta:=CASE WHEN r.buy_trader_id=who THEN r.quantity::numeric ELSE -r.quantity::numeric END;
      px:=r.price_ticks::numeric*r.tick_size;
      IF q=0 THEN an:=px; ad:=1;
      ELSIF sign(q)=sign(delta) THEN
        an:=an*abs(q)+px*abs(delta)*ad; ad:=ad*(abs(q)+abs(delta));
        g:=gcd(abs(an),ad); an:=div(an,g); ad:=div(ad,g);
      ELSE
        closed:=least(abs(q),abs(delta));
        change_n:=closed*(px*ad-an)*sign(q);
        pn:=pn*ad+change_n*pd; pd:=pd*ad;
        g:=gcd(abs(pn),pd); pn:=div(pn,g); pd:=div(pd,g);
        IF abs(delta)>abs(q) THEN an:=px; ad:=1; END IF;
      END IF;
      q:=q+delta;
      IF q=0 THEN an:=0; ad:=1; END IF;
    END LOOP;
    INSERT INTO public.position(trader_id,instrument_id,net_quantity,realized_pnl)
      VALUES(who,NEW.instrument_id,q::bigint,(sign(pn)*div(2*abs(pn)+pd,2*pd))::bigint)
      ON CONFLICT(trader_id,instrument_id) DO UPDATE SET net_quantity=EXCLUDED.net_quantity,
         realized_pnl=EXCLUDED.realized_pnl,updated_at=now();
  END LOOP;
  RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.recompute_position() FROM PUBLIC;
DROP TRIGGER IF EXISTS execution_positions ON public.execution;
CREATE TRIGGER execution_positions AFTER INSERT ON public.execution FOR EACH ROW EXECUTE FUNCTION public.recompute_position();

-- Freeze historical fee/tick bases for the bounded academic demonstration.
CREATE OR REPLACE FUNCTION public.guard_financial_basis() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
  IF TG_TABLE_NAME='fee_tier' THEN
    IF TG_OP='UPDATE' AND NEW.maker_fee_bps=OLD.maker_fee_bps AND NEW.taker_fee_bps=OLD.taker_fee_bps THEN RETURN NEW; END IF;
  ELSIF TG_TABLE_NAME='margin_account' THEN
    IF NEW.fee_tier_id=OLD.fee_tier_id THEN RETURN NEW; END IF;
  ELSE
    IF NEW.tick_size=OLD.tick_size AND NEW.lot_size=OLD.lot_size THEN RETURN NEW; END IF;
  END IF;
  -- A hard demo freeze also closes the first-reservation versus metadata-update
  -- race. Inserts with their original basis remain allowed; no historical base
  -- is ever guessed or changed after admission.
  RAISE EXCEPTION 'Financial basis is immutable during the backend demo' USING ERRCODE='22023';
END $$;
REVOKE ALL ON FUNCTION public.guard_financial_basis() FROM PUBLIC;
DROP TRIGGER IF EXISTS fixed_fee_schedule ON public.fee_tier;
CREATE TRIGGER fixed_fee_schedule BEFORE UPDATE OF maker_fee_bps,taker_fee_bps OR DELETE ON public.fee_tier FOR EACH ROW EXECUTE FUNCTION public.guard_financial_basis();
DROP TRIGGER IF EXISTS fixed_fee_assignment ON public.margin_account;
CREATE TRIGGER fixed_fee_assignment BEFORE UPDATE OF fee_tier_id ON public.margin_account FOR EACH ROW EXECUTE FUNCTION public.guard_financial_basis();
DROP TRIGGER IF EXISTS fixed_instrument_basis ON public.instrument;
CREATE TRIGGER fixed_instrument_basis BEFORE UPDATE OF tick_size,lot_size ON public.instrument FOR EACH ROW EXECUTE FUNCTION public.guard_financial_basis();
