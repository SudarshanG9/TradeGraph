-- Executed quantity, not resting order depth. Parameters: minimum volume.
SELECT instrument_id, price_ticks, SUM(quantity) AS band_volume
FROM public.execution
GROUP BY instrument_id, price_ticks
HAVING SUM(quantity) > %(minimum_volume)s
ORDER BY instrument_id, price_ticks;
