-- name: maker_taker
WITH makers AS (
 SELECT CASE WHEN buy_order_id<sell_order_id THEN buy_trader_id ELSE sell_trader_id END AS trader_id FROM public.execution
), takers AS (
 SELECT CASE WHEN buy_order_id>sell_order_id THEN buy_trader_id ELSE sell_trader_id END AS trader_id FROM public.execution
)
SELECT 'both' AS classification,trader_id FROM (SELECT trader_id FROM makers INTERSECT SELECT trader_id FROM takers) x
UNION ALL
SELECT 'maker_only',trader_id FROM (SELECT trader_id FROM makers EXCEPT SELECT trader_id FROM takers) x
UNION ALL
SELECT 'either',trader_id FROM (SELECT trader_id FROM makers UNION SELECT trader_id FROM takers) x
ORDER BY classification,trader_id;

-- name: nested_range
-- Nested scalar subquery: active orders above the historical average price.
SELECT id,price_ticks FROM public."order" WHERE instrument_id=%(instrument_id)s AND price_ticks >
 (SELECT avg(price_ticks) FROM public.execution WHERE instrument_id=%(instrument_id)s) ORDER BY id;

-- name: correlated_orders
-- Correlated subquery: an order above that trader's own average order price.
SELECT o.id,o.trader_id,o.price_ticks FROM public."order" o WHERE o.price_ticks >
 (SELECT avg(other.price_ticks) FROM public."order" other WHERE other.trader_id=o.trader_id) ORDER BY o.id;
