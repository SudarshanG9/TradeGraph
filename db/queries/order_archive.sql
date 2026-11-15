-- One atomic DELETE RETURNING -> INSERT. Terminal status certifies routine commit.
-- Parameter cutoff is an aware timestamp; no active or unsettled order is eligible.
WITH moved AS (
 DELETE FROM public."order" o
 WHERE o.status IN ('FILLED','CANCELLED') AND o.updated_at < %(cutoff)s
   AND (%(trader_ids)s::uuid[] IS NULL OR o.trader_id=ANY(%(trader_ids)s))
   AND o.filled_quantity=(SELECT coalesce(sum(e.quantity),0) FROM public.execution e WHERE e.buy_order_id=o.id OR e.sell_order_id=o.id)
 RETURNING o.*
)
INSERT INTO public.order_history(id,trader_id,instrument_id,side,price_ticks,quantity,filled_quantity,status,created_at,updated_at)
SELECT id,trader_id,instrument_id,side,price_ticks,quantity,filled_quantity,status,created_at,updated_at FROM moved
RETURNING *;
