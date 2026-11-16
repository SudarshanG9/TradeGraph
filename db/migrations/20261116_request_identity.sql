-- Approved supplementary persistence. Apply as schema owner; no financial rows changed.
-- Default runtime login below: adapt this grant if POSTGRES_RUNTIME_USER differs.
BEGIN;
CREATE TABLE public.order_request_identity (
    trader_id UUID NOT NULL REFERENCES public.trader(id),
    request_key TEXT NOT NULL CHECK (request_key ~ '^[A-Za-z0-9._-]{1,128}$'),
    request_hash TEXT NOT NULL CHECK (request_hash ~ '^[0-9a-f]{64}$'),
    order_id BIGINT NOT NULL CHECK (order_id > 0),
    accepted_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (trader_id, request_key)
);
-- No FK to the hot order table: identities must outlive archival. The original
-- accepted response is exactly (order_id, constant OPEN, accepted_at).
REVOKE ALL ON public.order_request_identity FROM PUBLIC, trader_role, compliance_admin_role;
GRANT SELECT, INSERT ON public.order_request_identity TO tradegraph_runtime;
COMMIT;
-- Rollback: disable keyed traffic, reconcile/drain, retain identities read-only.
-- Never DROP this table while a previously used key can be replayed.
