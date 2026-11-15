-- Compatible physical access paths; no changes to the ER or canonical columns.
CREATE INDEX IF NOT EXISTS idx_execution_time_brin ON public.execution USING brin(executed_at) WITH(pages_per_range=4);
CREATE INDEX IF NOT EXISTS idx_execution_price_cover ON public.execution(instrument_id,price_ticks) INCLUDE(quantity,executed_at);
