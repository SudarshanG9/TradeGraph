CREATE OR REPLACE FUNCTION public.order_fee(p_order bigint) RETURNS numeric
LANGUAGE sql VOLATILE SET search_path=pg_catalog,pg_temp AS $$
 SELECT ceil(coalesce(sum(e.price_ticks::numeric*i.tick_size*e.quantity*
   CASE WHEN p_order=greatest(e.buy_order_id,e.sell_order_id) THEN f.taker_fee_bps ELSE f.maker_fee_bps END *0.0001),0))
 FROM public.execution e JOIN public.instrument i ON i.id=e.instrument_id
 JOIN public.margin_account m ON m.trader_id=CASE WHEN e.buy_order_id=p_order THEN e.buy_trader_id ELSE e.sell_trader_id END
 JOIN public.fee_tier f ON f.id=m.fee_tier_id
 WHERE e.buy_order_id=p_order OR e.sell_order_id=p_order
$$;
REVOKE ALL ON FUNCTION public.order_fee(bigint) FROM PUBLIC;

CREATE OR REPLACE FUNCTION public.settle_execution(
 p_event bigint,p_instrument integer,p_buy bigint,p_sell bigint,p_buyer uuid,p_seller uuid,
 p_price bigint,p_quantity bigint,p_taker bigint,p_time timestamptz
) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE b public."order"%ROWTYPE; s public."order"%ROWTYPE; old public.execution%ROWTYPE;
        tick integer; lot integer; bw numeric; sw numeric; qb numeric; qs numeric;
        bf0 numeric; bf1 numeric; sf0 numeric; sf1 numeric; br numeric; sr numeric;
        value numeric; seller_before numeric; buyer_refund numeric:=0; seller_fee numeric; count_accounts integer;
BEGIN
 IF p_event IS NULL OR p_event<=0 OR p_instrument IS NULL OR p_buy IS NULL OR p_sell IS NULL OR
    p_buyer IS NULL OR p_seller IS NULL OR p_price IS NULL OR p_quantity IS NULL OR p_time IS NULL OR
    p_taker IS NULL OR p_buy=p_sell OR p_buyer=p_seller OR p_price<=0 OR p_quantity<=0 OR
    p_taker<>greatest(p_buy,p_sell) THEN
   RAISE EXCEPTION 'Invalid execution identity' USING ERRCODE='22023';
 END IF;
 PERFORM pg_advisory_xact_lock(p_event);
 SELECT * INTO old FROM public.execution WHERE id=p_event;
 IF FOUND THEN
   IF old.instrument_id=p_instrument AND old.buy_order_id=p_buy AND old.sell_order_id=p_sell AND
      old.buy_trader_id=p_buyer AND old.sell_trader_id=p_seller AND old.price_ticks=p_price AND
      old.quantity=p_quantity AND old.executed_at=p_time THEN RETURN false; END IF;
   RAISE EXCEPTION 'Conflicting execution replay' USING ERRCODE='23505';
 END IF;
 -- Every two-account money path takes accounts, then orders, in the same order.
 PERFORM trader_id FROM public.margin_account WHERE trader_id IN(p_buyer,p_seller) ORDER BY trader_id FOR UPDATE;
 GET DIAGNOSTICS count_accounts=ROW_COUNT;
 IF count_accounts<>2 THEN RAISE EXCEPTION 'Missing counterparty account' USING ERRCODE='22023'; END IF;
 PERFORM id FROM public."order" WHERE id IN(p_buy,p_sell) ORDER BY id FOR UPDATE;
 SELECT * INTO b FROM public."order" WHERE id=p_buy;
 SELECT * INTO s FROM public."order" WHERE id=p_sell;
 IF b.id IS NULL OR s.id IS NULL OR b.trader_id<>p_buyer OR s.trader_id<>p_seller OR
    b.instrument_id<>p_instrument OR s.instrument_id<>p_instrument OR b.side<>'BUY' OR s.side<>'SELL' OR
    b.status NOT IN('OPEN','PARTIAL') OR s.status NOT IN('OPEN','PARTIAL') OR
    p_quantity>b.quantity-b.filled_quantity OR p_quantity>s.quantity-s.filled_quantity OR
    p_price>b.price_ticks OR p_price<s.price_ticks OR
    p_price<>(CASE WHEN p_buy<p_sell THEN b.price_ticks ELSE s.price_ticks END) THEN
   RAISE EXCEPTION 'Execution violates committed order/maker state' USING ERRCODE='22023';
 END IF;
 SELECT tick_size,lot_size INTO tick,lot FROM public.instrument WHERE id=p_instrument;
 IF mod(p_quantity,lot)<>0 THEN RAISE EXCEPTION 'Execution lot violation' USING ERRCODE='22023'; END IF;
 SELECT greatest(f.maker_fee_bps,f.taker_fee_bps)*0.0001 INTO bw FROM public.margin_account m JOIN public.fee_tier f ON f.id=m.fee_tier_id WHERE m.trader_id=p_buyer;
 SELECT greatest(f.maker_fee_bps,f.taker_fee_bps)*0.0001 INTO sw FROM public.margin_account m JOIN public.fee_tier f ON f.id=m.fee_tier_id WHERE m.trader_id=p_seller;
 qb:=b.quantity::numeric-b.filled_quantity; qs:=s.quantity::numeric-s.filled_quantity;
 bf0:=ceil(b.price_ticks::numeric*tick*qb*bw); bf1:=ceil(b.price_ticks::numeric*tick*(qb-p_quantity)*bw);
 sf0:=ceil(s.price_ticks::numeric*tick*qs*sw); sf1:=ceil(s.price_ticks::numeric*tick*(qs-p_quantity)*sw);
 br:=b.price_ticks::numeric*tick*p_quantity+bf0-bf1;
 sr:=s.price_ticks::numeric*tick*p_quantity+sf0-sf1;
 value:=p_price::numeric*tick*p_quantity;
 IF (SELECT escrow_balance FROM public.margin_account WHERE trader_id=p_buyer)<b.price_ticks::numeric*tick*qb+bf0 OR
    (SELECT escrow_balance FROM public.margin_account WHERE trader_id=p_seller)<s.price_ticks::numeric*tick*qs+sf0 THEN
   RAISE EXCEPTION 'Insufficient committed escrow' USING ERRCODE='22023';
 END IF;
 seller_before:=public.order_fee(p_sell);
 INSERT INTO public.execution(id,instrument_id,buy_order_id,sell_order_id,buy_trader_id,sell_trader_id,price_ticks,quantity,executed_at)
 VALUES(p_event,p_instrument,p_buy,p_sell,p_buyer,p_seller,p_price,p_quantity,p_time);
 seller_fee:=public.order_fee(p_sell)-seller_before;
 IF qb=p_quantity THEN
   buyer_refund:=ceil(b.price_ticks::numeric*tick*b.quantity*bw)-public.order_fee(p_buy);
   IF buyer_refund<0 THEN RAISE EXCEPTION 'BUY fee exceeds budget' USING ERRCODE='22023'; END IF;
 END IF;
 UPDATE public.margin_account SET cash_balance=(cash_balance::numeric+br-value-(bf0-bf1)+buyer_refund)::bigint,
   escrow_balance=(escrow_balance::numeric-br)::bigint,updated_at=now() WHERE trader_id=p_buyer;
 UPDATE public.margin_account SET cash_balance=(cash_balance::numeric+sr+value-seller_fee)::bigint,
   escrow_balance=(escrow_balance::numeric-sr)::bigint,updated_at=now() WHERE trader_id=p_seller;
 UPDATE public."order" SET filled_quantity=filled_quantity+p_quantity,
   status=CASE WHEN filled_quantity+p_quantity=quantity THEN 'FILLED' ELSE 'PARTIAL' END,updated_at=now() WHERE id IN(p_buy,p_sell);
 RETURN true;
END $$;
REVOKE ALL ON FUNCTION public.settle_execution(bigint,integer,bigint,bigint,uuid,uuid,bigint,bigint,bigint,timestamptz) FROM PUBLIC,trader_role,compliance_admin_role;
