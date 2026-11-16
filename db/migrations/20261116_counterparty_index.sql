-- Owner deployment outside a transaction; rollback DROP INDEX CONCURRENTLY public.idx_execution_counterparty_pair.
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_execution_counterparty_pair
ON public.execution(buy_trader_id,sell_trader_id)
INCLUDE(instrument_id,price_ticks,quantity,executed_at);
