-- Additive observation ordering only; vector dimensions/feature mathematics unchanged.
-- NULL means historical order was never recorded; do not invent that metadata.
ALTER TABLE public.regime_snapshot ADD COLUMN IF NOT EXISTS observed_at timestamptz;
ALTER TABLE public.regime_snapshot ADD COLUMN IF NOT EXISTS observation_execution_id bigint;
-- Compatibility for a draining old observation writer: timestamp only actual new
-- writes, never backfill historical rows with today's time.
CREATE OR REPLACE FUNCTION public.stamp_regime_observation() RETURNS trigger
LANGUAGE plpgsql SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 IF TG_OP='INSERT' THEN
   IF NEW.observed_at IS NULL THEN NEW.observed_at:=clock_timestamp(); END IF;
 ELSIF NEW.observed_at IS NOT DISTINCT FROM OLD.observed_at
       AND NEW.observation_execution_id IS NOT DISTINCT FROM OLD.observation_execution_id THEN
   NEW.observed_at:=clock_timestamp();
   NEW.observation_execution_id:=NULL;
 END IF;
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.stamp_regime_observation() FROM PUBLIC;
DROP TRIGGER IF EXISTS regime_observation_order ON public.regime_snapshot;
CREATE TRIGGER regime_observation_order BEFORE INSERT OR UPDATE OF features ON public.regime_snapshot
 FOR EACH ROW EXECUTE FUNCTION public.stamp_regime_observation();
