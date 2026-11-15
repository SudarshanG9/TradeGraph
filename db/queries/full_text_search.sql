SELECT id,instrument_id,title,published_at,ts_rank(body_tsv,websearch_to_tsquery('english',%(q)s)) AS rank
FROM public.market_disclosure
WHERE body_tsv @@ websearch_to_tsquery('english',%(q)s)
ORDER BY rank DESC,id DESC LIMIT %(limit)s;
