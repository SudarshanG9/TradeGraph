-- Template applied by scripts/setup_database_identity.py with quoted role identifiers.
-- Requires maintenance cutover to the new isolated-identity API configuration.
-- Does not modify any core table column, financial routine or existing login.
GRANT USAGE ON SCHEMA public TO {financial_role}, {auth_role}, {compliance_role};
GRANT trader_role TO {financial_role};
-- Financial service deliberately cannot SET ROLE compliance_admin_role.
GRANT compliance_admin_role TO {compliance_role};
GRANT SELECT ON public.instrument,public.fee_tier,public.desk,public.margin_account,
 public."order",public.order_history,public.execution,public.position TO {financial_role};
GRANT SELECT(id,email,role) ON public.user_account TO {financial_role};
GRANT SELECT(id,user_account_id,desk_id,full_name) ON public.trader TO {financial_role};
GRANT SELECT,INSERT ON public.order_request_identity TO {financial_role};
GRANT USAGE ON SEQUENCE public.execution_id_seq TO {financial_role};
GRANT EXECUTE ON FUNCTION public.place_and_reserve_order(uuid,integer,text,bigint,bigint),
 public.cancel_order(bigint,uuid),
 public.settle_execution(bigint,integer,bigint,bigint,uuid,uuid,bigint,bigint,bigint,timestamptz),
 public.archive_terminal_orders(timestamptz,integer,uuid[]) TO {financial_role};
GRANT SELECT(id,email,password_hash,role) ON public.user_account TO {auth_role};
GRANT SELECT(id,user_account_id) ON public.trader TO {auth_role};
GRANT SELECT ON public.margin_account,public."order",public.order_history,
 public.position,public.order_request_identity TO trader_role;
CREATE OR REPLACE FUNCTION public.rls_trader_id() RETURNS uuid
LANGUAGE sql STABLE SET search_path=pg_catalog,pg_temp AS $$
 SELECT CASE WHEN left(session_user::text,3)='tg_' AND length(session_user::text)=39
 THEN substring(session_user::text FROM 4)::uuid ELSE NULL END
$$;
REVOKE ALL ON FUNCTION public.rls_trader_id() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.rls_trader_id() TO trader_role;

ALTER TABLE public."margin_account" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."margin_account" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_trader_read ON public."margin_account";
CREATE POLICY own_trader_read ON public."margin_account" FOR SELECT TO trader_role
 USING (trader_id=public.rls_trader_id());
DROP POLICY IF EXISTS financial_service_read ON public."margin_account";
CREATE POLICY financial_service_read ON public."margin_account" FOR SELECT TO {financial_role} USING (true);
DROP POLICY IF EXISTS compliance_financial_read ON public."margin_account";
CREATE POLICY compliance_financial_read ON public."margin_account" FOR SELECT TO compliance_admin_role USING (true);

ALTER TABLE public."order" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."order" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_trader_read ON public."order";
CREATE POLICY own_trader_read ON public."order" FOR SELECT TO trader_role
 USING (trader_id=public.rls_trader_id());
DROP POLICY IF EXISTS financial_service_read ON public."order";
CREATE POLICY financial_service_read ON public."order" FOR SELECT TO {financial_role} USING (true);
DROP POLICY IF EXISTS compliance_financial_read ON public."order";
CREATE POLICY compliance_financial_read ON public."order" FOR SELECT TO compliance_admin_role USING (true);

ALTER TABLE public."order_history" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."order_history" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_trader_read ON public."order_history";
CREATE POLICY own_trader_read ON public."order_history" FOR SELECT TO trader_role
 USING (trader_id=public.rls_trader_id());
DROP POLICY IF EXISTS financial_service_read ON public."order_history";
CREATE POLICY financial_service_read ON public."order_history" FOR SELECT TO {financial_role} USING (true);
DROP POLICY IF EXISTS compliance_financial_read ON public."order_history";
CREATE POLICY compliance_financial_read ON public."order_history" FOR SELECT TO compliance_admin_role USING (true);

ALTER TABLE public."position" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."position" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_trader_read ON public."position";
CREATE POLICY own_trader_read ON public."position" FOR SELECT TO trader_role
 USING (trader_id=public.rls_trader_id());
DROP POLICY IF EXISTS financial_service_read ON public."position";
CREATE POLICY financial_service_read ON public."position" FOR SELECT TO {financial_role} USING (true);
DROP POLICY IF EXISTS compliance_financial_read ON public."position";
CREATE POLICY compliance_financial_read ON public."position" FOR SELECT TO compliance_admin_role USING (true);

ALTER TABLE public."order_request_identity" ENABLE ROW LEVEL SECURITY;
ALTER TABLE public."order_request_identity" FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS own_trader_read ON public."order_request_identity";
CREATE POLICY own_trader_read ON public."order_request_identity" FOR SELECT TO trader_role
 USING (trader_id=public.rls_trader_id());
DROP POLICY IF EXISTS financial_service_read ON public."order_request_identity";
CREATE POLICY financial_service_read ON public."order_request_identity" FOR SELECT TO {financial_role} USING (true);
DROP POLICY IF EXISTS compliance_financial_read ON public."order_request_identity";
CREATE POLICY compliance_financial_read ON public."order_request_identity" FOR SELECT TO compliance_admin_role USING (true);

DROP POLICY IF EXISTS financial_request_insert ON public.order_request_identity;
CREATE POLICY financial_request_insert ON public.order_request_identity FOR INSERT
 TO {financial_role} WITH CHECK (true);
-- Rollback: stop new API traffic, drain connections, remove only the policies above,
-- DISABLE/FORCE settings on these five tables, restore reviewed legacy role grants.
-- Keep request identity rows and all financial rows. Never rotate the running API
-- credentials or revoke existing roles as part of this template.
