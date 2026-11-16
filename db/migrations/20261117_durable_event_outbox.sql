-- Apply under the installation owner in a transaction, before enabling new workers.
-- No financial routine or financial arithmetic is changed.
CREATE TABLE IF NOT EXISTS public.event_outbox (
 execution_id bigint NOT NULL REFERENCES public.execution(id) ON DELETE CASCADE,
 consumer text NOT NULL CHECK (consumer IN ('graph','regime')),
 event_type text NOT NULL DEFAULT 'execution.committed' CHECK (event_type='execution.committed'),
 schema_version integer NOT NULL DEFAULT 1 CHECK (schema_version=1),
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 payload jsonb,
 completed_at timestamptz,
 attempts integer NOT NULL DEFAULT 0 CHECK (attempts>=0),
 next_attempt_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 last_error varchar(120),
 PRIMARY KEY (execution_id,consumer)
);
REVOKE ALL ON public.event_outbox FROM PUBLIC,trader_role,compliance_admin_role;
CREATE INDEX IF NOT EXISTS event_outbox_pending ON public.event_outbox(consumer,next_attempt_at,execution_id)
 WHERE completed_at IS NULL;
CREATE OR REPLACE FUNCTION public.track_execution_publication() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
BEGIN
 INSERT INTO public.event_outbox(execution_id,consumer) VALUES(NEW.id,'graph'),(NEW.id,'regime');
 RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION public.track_execution_publication() FROM PUBLIC;
DROP TRIGGER IF EXISTS execution_publication ON public.execution;
CREATE TRIGGER execution_publication AFTER INSERT ON public.execution
 FOR EACH ROW EXECUTE FUNCTION public.track_execution_publication();
-- Installation backfill is atomic with trigger creation. No invented regime history.
INSERT INTO public.event_outbox(execution_id,consumer)
 SELECT e.id,c.consumer FROM public.execution e CROSS JOIN (VALUES('graph'),('regime')) c(consumer)
 ON CONFLICT DO NOTHING;
