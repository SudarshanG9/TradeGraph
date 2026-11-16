-- Bounded internal maintenance, no direct financial-table write grant.
BEGIN;
CREATE OR REPLACE FUNCTION public.archive_terminal_orders(p_cutoff timestamptz,p_batch integer,p_traders uuid[] DEFAULT NULL)
RETURNS SETOF public.order_history LANGUAGE plpgsql SECURITY DEFINER
SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF p_cutoff IS NULL OR p_batch IS NULL OR p_batch<1 OR p_batch>10000 THEN
   RAISE EXCEPTION 'Invalid archive batch' USING ERRCODE='22023';
 END IF;
 RETURN QUERY
-- One atomic DELETE RETURNING -> INSERT. Terminal status certifies routine commit.
-- Parameter cutoff is an aware timestamp; no active or unsettled order is eligible.
WITH candidates AS MATERIALIZED (
 SELECT o.id FROM public."order" o
 WHERE o.status IN ('FILLED','CANCELLED') AND o.updated_at < p_cutoff
   AND (p_traders::uuid[] IS NULL OR o.trader_id=ANY(p_traders))
 ORDER BY o.updated_at,o.id LIMIT p_batch
 FOR UPDATE SKIP LOCKED
), moved AS (
 DELETE FROM public."order" o USING candidates c
 WHERE o.id=c.id AND o.status IN ('FILLED','CANCELLED') AND o.updated_at < p_cutoff
   AND (p_traders::uuid[] IS NULL OR o.trader_id=ANY(p_traders))
   AND o.filled_quantity=(SELECT coalesce(sum(e.quantity),0) FROM public.execution e WHERE e.buy_order_id=o.id OR e.sell_order_id=o.id)
 RETURNING o.*
)
INSERT INTO public.order_history(id,trader_id,instrument_id,side,price_ticks,quantity,filled_quantity,status,created_at,updated_at)
SELECT id,trader_id,instrument_id,side,price_ticks,quantity,filled_quantity,status,created_at,updated_at FROM moved
RETURNING *;

END;
$$;
REVOKE ALL ON FUNCTION public.archive_terminal_orders(timestamptz,integer,uuid[]) FROM PUBLIC,trader_role,compliance_admin_role;
GRANT EXECUTE ON FUNCTION public.archive_terminal_orders(timestamptz,integer,uuid[]) TO tradegraph_runtime;
COMMIT;
-- Rollback: disable maintenance, drain task, DROP FUNCTION public.archive_terminal_orders(timestamptz,integer,uuid[]);
-- Archived rows remain valid canonical history; never move them back during live trading.
