-- Compatible physical access paths; no changes to the ER or canonical columns.
CREATE INDEX IF NOT EXISTS idx_execution_time_brin ON public.execution USING brin(executed_at) WITH(pages_per_range=4);
CREATE INDEX IF NOT EXISTS idx_execution_price_cover ON public.execution(instrument_id,price_ticks) INCLUDE(quantity,executed_at);

-- Historical fee/archival OR lookups and instrument-scoped position replay.
CREATE INDEX IF NOT EXISTS idx_execution_buy_order ON public.execution(buy_order_id);
CREATE INDEX IF NOT EXISTS idx_execution_sell_order ON public.execution(sell_order_id);
CREATE INDEX IF NOT EXISTS idx_execution_buy_instrument_id ON public.execution(buy_trader_id,instrument_id,id);
CREATE INDEX IF NOT EXISTS idx_execution_sell_instrument_id ON public.execution(sell_trader_id,instrument_id,id);
