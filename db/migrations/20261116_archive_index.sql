-- Run outside a transaction; rollback DROP INDEX CONCURRENTLY public.idx_order_archive_candidates.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_order_archive_candidates
ON public."order"(updated_at,id) WHERE status IN ('FILLED','CANCELLED');
