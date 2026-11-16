-- Maintenance rollback of public registration only. Preserve all accounts/status
-- so pending/disabled users cannot silently become eligible for legacy login.
REVOKE ALL ON FUNCTION public.register_trader(text,text,text) FROM PUBLIC;
DROP FUNCTION public.register_trader(text,text,text);
-- Keep registration_state, registration_policy and normalized uniqueness.
-- Do not roll backend below readiness enforcement while pending users exist.
