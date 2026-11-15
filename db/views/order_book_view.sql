-- Persisted active-order teaching view; never used by the matching hot path.
CREATE OR REPLACE VIEW public.order_book_view AS
SELECT instrument_id,side,price_ticks,SUM(quantity-filled_quantity) AS remaining_quantity
FROM public."order" WHERE status IN ('OPEN','PARTIAL')
GROUP BY instrument_id,side,price_ticks;
GRANT SELECT ON public.order_book_view TO compliance_admin_role;
