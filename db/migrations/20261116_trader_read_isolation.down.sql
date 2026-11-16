-- Controlled rollback only: stop isolated API traffic and drain all connections.
-- Retains financial/request data and new credentials; does not reset any password.
BEGIN;
DROP POLICY IF EXISTS own_trader_read ON public."margin_account";
DROP POLICY IF EXISTS financial_service_read ON public."margin_account";
DROP POLICY IF EXISTS compliance_financial_read ON public."margin_account";
ALTER TABLE public."margin_account" NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public."margin_account" DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_trader_read ON public."order";
DROP POLICY IF EXISTS financial_service_read ON public."order";
DROP POLICY IF EXISTS compliance_financial_read ON public."order";
ALTER TABLE public."order" NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public."order" DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_trader_read ON public."order_history";
DROP POLICY IF EXISTS financial_service_read ON public."order_history";
DROP POLICY IF EXISTS compliance_financial_read ON public."order_history";
ALTER TABLE public."order_history" NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public."order_history" DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_trader_read ON public."position";
DROP POLICY IF EXISTS financial_service_read ON public."position";
DROP POLICY IF EXISTS compliance_financial_read ON public."position";
ALTER TABLE public."position" NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public."position" DISABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_trader_read ON public."order_request_identity";
DROP POLICY IF EXISTS financial_service_read ON public."order_request_identity";
DROP POLICY IF EXISTS compliance_financial_read ON public."order_request_identity";
DROP POLICY IF EXISTS financial_request_insert ON public."order_request_identity";
ALTER TABLE public."order_request_identity" NO FORCE ROW LEVEL SECURITY;
ALTER TABLE public."order_request_identity" DISABLE ROW LEVEL SECURITY;
REVOKE SELECT ON public.margin_account,public."order",public.order_history,
 public.position,public.order_request_identity FROM trader_role;
DROP FUNCTION public.rls_trader_id();
COMMIT;
-- Restore explicit legacy API credentials/config only after reviewing baseline grants.
-- New audit/service logins can be retired separately after no connection uses them.
