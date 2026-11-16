-- Ordinary runtime reads need these authentication/identity columns only.
-- compliance_admin_role access remains explicit via SET LOCAL ROLE.
-- Adapt the default login if POSTGRES_RUNTIME_USER differs. Apply as owner.
BEGIN;
REVOKE SELECT ON public.user_account, public.trader FROM tradegraph_runtime;
GRANT SELECT(id,email,password_hash,role) ON public.user_account TO tradegraph_runtime;
GRANT SELECT(id,user_account_id,desk_id,full_name) ON public.trader TO tradegraph_runtime;
COMMIT;
-- Rollback (owner): GRANT SELECT ON public.user_account,public.trader TO tradegraph_runtime;
