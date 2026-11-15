SELECT id,instrument_id,captured_at,features::text AS features,features <=> %(features)s::vector AS cosine_distance
FROM public.regime_snapshot
WHERE (%(instrument_id)s::integer IS NULL OR instrument_id=%(instrument_id)s)
ORDER BY features <=> %(features)s::vector LIMIT %(limit)s;
