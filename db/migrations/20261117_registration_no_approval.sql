-- Automatic trader setup; funding, KYC and administrator roles are unchanged.
CREATE OR REPLACE FUNCTION public.register_trader(p_email text,p_hash text,p_name text)
RETURNS TABLE(registration_id uuid,status text)
LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,pg_temp AS $$
DECLARE uid uuid; tid uuid; tier integer; policy public.registration_policy%ROWTYPE;
BEGIN
 IF p_email IS NULL OR p_email<>lower(btrim(p_email)) OR length(p_email)>255
    OR p_email !~ '^[a-z0-9.!#$%&''*+/=?^_`|~-]+@[a-z0-9.-]+\.[a-z]{{2,}}$'
    OR p_name IS NULL OR length(btrim(p_name))<2 OR length(p_name)>150
    OR p_hash IS NULL OR p_hash !~ '^\$2[aby]\$[0-9]{{2}}\$[./A-Za-z0-9]{{53}}$'
 THEN RAISE EXCEPTION 'Invalid registration' USING ERRCODE='22023'; END IF;
 SELECT * INTO STRICT policy FROM public.registration_policy WHERE singleton;
 SELECT id INTO STRICT tier FROM public.fee_tier WHERE tier_name='STANDARD';
 INSERT INTO public.user_account(email,password_hash,role) VALUES(p_email,p_hash,'TRADER') RETURNING id INTO uid;
 INSERT INTO public.trader(user_account_id,full_name) VALUES(uid,btrim(p_name)) RETURNING id INTO tid;
 INSERT INTO public.margin_account(trader_id,cash_balance,fee_tier_id) VALUES(tid,policy.initial_cash,tier);
 INSERT INTO public.registration_state(user_account_id,trader_id,status)
 VALUES(uid,tid,'PENDING_PROVISIONING');
 RETURN QUERY SELECT uid,r.status FROM public.registration_state r WHERE r.user_account_id=uid;
END $$;
REVOKE ALL ON FUNCTION public.register_trader(text,text,text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.register_trader(text,text,text) TO {auth_role};

UPDATE public.registration_state SET status='PENDING_PROVISIONING',updated_at=now() WHERE status='PENDING_VERIFICATION';
