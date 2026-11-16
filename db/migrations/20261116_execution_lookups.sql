-- ONLINE alternative to setup_backend.sh, which wraps ordinary index DDL in a transaction.
-- Operator: run psql in autocommit mode WITHOUT -1/--single-transaction.
-- Inspect existing definitions and invalid indexes before retrying an interrupted build.
-- IF NOT EXISTS does not repair an invalid index or validate an existing definition.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_execution_buy_order ON public.execution(buy_order_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_execution_sell_order ON public.execution(sell_order_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_execution_buy_instrument_id ON public.execution(buy_trader_id,instrument_id,id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_execution_sell_instrument_id ON public.execution(sell_trader_id,instrument_id,id);
-- Reversal (autocommit; only indexes created by this migration):
-- DROP INDEX CONCURRENTLY public.idx_execution_buy_order;
-- DROP INDEX CONCURRENTLY public.idx_execution_sell_order;
-- DROP INDEX CONCURRENTLY public.idx_execution_buy_instrument_id;
-- DROP INDEX CONCURRENTLY public.idx_execution_sell_instrument_id;
