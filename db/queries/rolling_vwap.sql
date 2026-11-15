-- Tick units; SQL time window differs from the in-memory last-N-fill ring.
SELECT id,instrument_id,executed_at,
 (SUM(price_ticks::numeric*quantity) OVER w / NULLIF(SUM(quantity) OVER w,0))::text AS vwap_ticks
FROM public.execution
WHERE instrument_id=%(instrument_id)s
WINDOW w AS(PARTITION BY instrument_id ORDER BY executed_at RANGE BETWEEN INTERVAL '10 minutes' PRECEDING AND CURRENT ROW)
ORDER BY executed_at,id;
