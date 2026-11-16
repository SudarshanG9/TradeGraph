"""Least-privileged service connections; every call has an explicit commit boundary."""
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from decimal import Decimal
from backend.config import ROOT
from backend.risk.request_identity import RequestIdentityStore, request_hash


QUERY_FILES = {
    'bands':'price_band_having.sql','rollup':'recursive_desk_rollup.sql',
    'vwap':'rolling_vwap.sql','archive':'order_archive.sql',
    'fts':'full_text_search.sql','similar':'vector_similarity.sql',
    'maker_taker':'set_operations.sql','nested_range':'set_operations.sql',
    'correlated_orders':'set_operations.sql',
}


def query_text(name):
    text = (ROOT / 'db' / 'queries' / QUERY_FILES[name]).read_text()
    if '-- name:' in text:
        sections = {part.split('\n',1)[0].strip():part.split('\n',1)[1] for part in text.split('-- name:')[1:]}
        text = sections[name]
    return text


def json_units(value):
    if isinstance(value, Decimal):
        return int(value) if value==value.to_integral_value() else str(value)
    if isinstance(value, dict): return {k:json_units(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)): return [json_units(v) for v in value]
    return value


class Database:
    def __init__(self, settings):
        self.settings = settings
        # Installed by startup on the owner loop. Snapshots are replaced, never
        # mutated; a settlement thread takes one immutable observation reference.
        self.regime_books = None

    def connect(self, **kwargs):
        s=self.settings
        return self._connect_as(s.postgres_runtime_user,s.postgres_runtime_password,**kwargs)

    def _connect_as(self,user,password,**kwargs):
        s = self.settings
        return psycopg.connect(host=s.postgres_host, port=s.postgres_port,
            dbname=s.postgres_db, user=user,
            password=password, connect_timeout=s.health_timeout_seconds,
            options='-c statement_timeout=30000 -c lock_timeout=10000',
            row_factory=dict_row, **kwargs)

    def query(self, sql, params=()):
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def archive_terminal_orders(self, cutoff, batch_size=100, trader_ids=None):
        if (getattr(cutoff, 'tzinfo', None) is None or cutoff.utcoffset() is None or
            type(batch_size) is not int or not 1 <= batch_size <= 10000):
            raise ValueError('Aware cutoff and bounded batch required')
        with self.connect() as conn:
            return conn.execute('SELECT * FROM public.archive_terminal_orders(%s,%s,%s::uuid[])',
                                (cutoff,batch_size,trader_ids)).fetchall()

    def execution_batches(self, batch_size=1000):
        """Server-side cursor, one read-only snapshot, bounded client materialization."""
        if type(batch_size) is not int or not 1 <= batch_size <= 10000:
            raise ValueError('Replay batch size must be 1..10000')
        with self.connect() as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            with conn.cursor(name='tradegraph_execution_replay') as cursor:
                cursor.execute('SELECT * FROM public.execution ORDER BY id')
                while rows := cursor.fetchmany(batch_size):
                    yield rows

    def iter_executions(self, batch_size=1000):
        for batch in self.execution_batches(batch_size):
            yield from batch

    def auth_query(self, sql, params=()):
        if self.settings.database_identity_mode=='legacy':
            return self.query(sql,params)
        with self._connect_as(self.settings.postgres_auth_user,self.settings.postgres_auth_password) as conn:
            conn.execute('SET TRANSACTION READ ONLY')
            return conn.execute(sql,params).fetchall()

    @contextmanager
    def trader_context(self,trader_id):
        if self.settings.database_identity_mode!='isolated':
            raise psycopg.OperationalError('Trusted trader identity mode is not configured')
        from backend.stores.trader_identity import credentials,trader_role
        user,password=credentials(self.settings.trader_credentials_file,trader_id)
        with self._connect_as(user,password) as conn:
            conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            conn.execute('SET LOCAL ROLE trader_role')
            actor=conn.execute("SELECT session_user AS login,current_user AS role,rolsuper,rolcreatedb,rolcreaterole,rolbypassrls,rolinherit,pg_has_role(session_user,%s,'MEMBER') AS financial_member,pg_has_role(session_user,'compliance_admin_role','MEMBER') AS admin_member FROM pg_roles WHERE rolname=session_user",(self.settings.postgres_runtime_user,)).fetchone()
            if (actor['login']!=trader_role(trader_id) or actor['role']!='trader_role' or
                any(actor[key] for key in ('rolsuper','rolcreatedb','rolcreaterole','rolbypassrls','rolinherit','financial_member','admin_member'))):
                raise psycopg.OperationalError('Database trader identity mismatch')
            yield conn

    def trader_query(self,trader_id,sql,params=()):
        if self.settings.database_identity_mode=='legacy':
            return self.query(sql,params)
        with self.trader_context(trader_id) as conn:
            return conn.execute(sql,params).fetchall()

    def account_snapshot(self,trader_id):
        context=self.trader_context(trader_id) if self.settings.database_identity_mode=='isolated' else self.connect()
        with context as conn:
            if self.settings.database_identity_mode!='isolated':
                conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
            row=conn.execute('SELECT trader_id,cash_balance,escrow_balance FROM margin_account WHERE trader_id=%s',(trader_id,)).fetchone()
            if row is None:return None
            positions=conn.execute("SELECT instrument_id,net_quantity,realized_pnl,'gross' AS pnl_basis FROM position WHERE trader_id=%s",(trader_id,)).fetchall()
            return row | {'positions':positions}

    def trader_request_identity(self,trader_id,key):
        rows=self.trader_query(trader_id,'SELECT * FROM public.order_request_identity WHERE trader_id=%s AND request_key=%s',(trader_id,key))
        return rows[0] if rows else None

    def registration_status(self, subject):
        rows = self.auth_query('SELECT status FROM public.registration_state WHERE user_account_id=%s', (subject,))
        return rows[0]['status'] if rows else None

    def identity(self, subject):
        rows = self.auth_query('SELECT u.id,u.role,t.id AS trader_id FROM user_account u LEFT JOIN trader t ON t.user_account_id=u.id WHERE u.id=%s', (subject,))
        return rows[0] if rows else None

    def named(self, name, params=None):
        if name=='archive':
            raise ValueError('Archival is an operator write, not a query endpoint')
        with self.admin_context() as conn:
            return json_units(conn.execute(query_text(name),params or {}).fetchall())

    def optimizer(self, scenario, instrument_id, lower, upper):
        if scenario=='price_band':
            query='SELECT SUM(quantity) FROM public.execution WHERE instrument_id=%s AND price_ticks BETWEEN %s AND %s'
            params=(instrument_id,lower,upper)
        elif scenario=='recent_executions':
            query="SELECT count(*) FROM public.execution WHERE executed_at >= now()-interval '10 minutes'"
            params=()
        else:
            raise ValueError('Unknown optimizer scenario')
        plans={}
        for mode in ('forced_sequential','automatic'):
            with self.admin_context() as conn:
                conn.execute('SET TRANSACTION READ ONLY')
                if mode=='forced_sequential':
                    conn.execute('SET LOCAL enable_indexscan=off')
                    conn.execute('SET LOCAL enable_indexonlyscan=off')
                    conn.execute('SET LOCAL enable_bitmapscan=off')
                plans[mode]=conn.execute('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+query,params).fetchone()['QUERY PLAN'][0]
        count=self.query('SELECT count(*) AS n FROM execution')[0]['n']
        return {'scenario':scenario,'row_count':int(plans['automatic']['Plan']['Actual Rows']),'dataset_size':count,'plans':plans}

    def request_identity(self, trader_id, key):
        rows = self.query('SELECT * FROM public.order_request_identity WHERE trader_id=%s AND request_key=%s',
                          (trader_id, key))
        return rows[0] if rows else None

    def reserve(self, trader_id, request, request_key=None):
        with self.connect() as conn:
            conn.execute("SET LOCAL app.role='TRADER'")
            if request_key is not None:
                # Hash collisions only serialize independent keys; uniqueness and
                # payload verification always use the full trader/key identity.
                conn.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s,0))',
                             (str(trader_id) + ':' + request_key,))
                identity = conn.execute('SELECT * FROM public.order_request_identity WHERE trader_id=%s AND request_key=%s',
                                        (trader_id, request_key)).fetchone()
                if identity:
                    return RequestIdentityStore.verify(identity, request)
            order_id = conn.execute('SELECT public.place_and_reserve_order(%s,%s,%s,%s,%s) AS id',
                (trader_id, request.instrument_id, request.side, request.price_ticks, request.quantity)).fetchone()['id']
            row = conn.execute('SELECT * FROM public."order" WHERE id=%s', (order_id,)).fetchone()
            if request_key is not None:
                conn.execute('INSERT INTO public.order_request_identity(trader_id,request_key,request_hash,order_id,accepted_at) VALUES (%s,%s,%s,%s,%s)',
                             (trader_id, request_key, request_hash(request), order_id, row['created_at']))
        return row  # context COMMIT completed before matcher admission

    def execution_ids(self, count):
        if not count:
            return []
        return [r['id'] for r in self.query("SELECT nextval('public.execution_id_seq') AS id FROM generate_series(1,%s)", (count,))]

    def settle(self, event):
        with self.connect() as conn:
            conn.execute("SET LOCAL app.role='TRADER'")
            applied = conn.execute('SELECT public.settle_execution(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) AS applied',
                (event.event_id,event.instrument_id,event.buy_order_id,event.sell_order_id,event.buy_trader_id,
                 event.sell_trader_id,event.price_ticks,event.quantity,event.taker_order_id,event.occurred_at)).fetchone()['applied']
            if applied and self.regime_books is not None:
                self.persist_regime_observation(conn, event)
        return applied  # financial acknowledgement only after COMMIT

    def persist_regime_observation(self, conn, event):
        """Persist the existing feature function's output inside settlement COMMIT.

        Historical executions without this observation are never reconstructed
        using today's book. A failed metadata write rolls back settlement too.
        """
        from datetime import datetime, timedelta, timezone
        from psycopg.types.json import Jsonb
        from backend.stores.regimes import market_features
        snapshot = self.regime_books.get(event.instrument_id)
        if snapshot is None:
            raise RuntimeError('Verified book observation required before settlement')
        now = datetime.now(timezone.utc)
        recent = conn.execute('SELECT price_ticks,quantity,executed_at FROM execution WHERE instrument_id=%s AND executed_at BETWEEN %s AND %s ORDER BY executed_at,id',
                              (event.instrument_id, now-timedelta(seconds=60), now)).fetchall()
        history = list(reversed(conn.execute('SELECT price_ticks,quantity FROM execution WHERE instrument_id=%s ORDER BY id DESC LIMIT 100',
                                             (event.instrument_id,)).fetchall()))
        features = market_features(snapshot['bids'], snapshot['asks'], recent, history)
        payload = {'features': features, 'observed_at': now.isoformat(),
                   'captured_at': now.replace(second=0, microsecond=0).isoformat(),
                   'book': snapshot}
        changed = conn.execute("UPDATE public.event_outbox SET payload=%s WHERE execution_id=%s AND consumer='regime' AND payload IS NULL RETURNING execution_id",
                               (Jsonb(payload), event.event_id)).fetchone()
        if changed is None:
            raise RuntimeError('Atomic regime publication intent missing')

    def cancel(self, order_id, trader_id):
        with self.connect() as conn:
            conn.execute("SET LOCAL app.role='TRADER'")
            quantity = conn.execute('SELECT public.cancel_order(%s,%s) AS quantity',(order_id,trader_id)).fetchone()['quantity']
        return quantity

    def reconcile_execution(self, event):
        """Confirm an exact canonical commit; absence is NOT permission to retry."""
        if event.taker_order_id != max(event.buy_order_id, event.sell_order_id):
            raise RuntimeError('Invalid execution taker; operator reconciliation required')
        rows = self.query('SELECT * FROM public.execution WHERE id=%s', (event.event_id,))
        if not rows:
            raise RuntimeError('Execution commit unresolved; operator reconciliation required')
        row = rows[0]
        expected = {'id':event.event_id, 'instrument_id':event.instrument_id,
            'buy_order_id':event.buy_order_id, 'sell_order_id':event.sell_order_id,
            'buy_trader_id':event.buy_trader_id, 'sell_trader_id':event.sell_trader_id,
            'price_ticks':event.price_ticks, 'quantity':event.quantity,
            'executed_at':event.occurred_at}
        if any(row[key] != value for key, value in expected.items()):
            raise RuntimeError('Conflicting committed execution; operator reconciliation required')
        return True

    def acquire_owner(self):
        if self.settings.database_identity_mode=='isolated':
            from backend.stores.trader_identity import verify_password_authentication
            s=self.settings
            for user in (s.postgres_runtime_user,s.postgres_auth_user,s.postgres_compliance_user):
                verify_password_authentication(s.postgres_host,s.postgres_port,s.postgres_db,user)
        conn = self.connect(autocommit=True)
        try:
            row = conn.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls,rolinherit FROM pg_roles WHERE rolname=current_user').fetchone()
            if any(row.values()):
                raise RuntimeError('Runtime login must be nonprivileged and NOINHERIT')
            if self.settings.database_identity_mode=='isolated':
                boundary=conn.execute("""SELECT pg_has_role(current_user,'compliance_admin_role','MEMBER') AS admin_member,
                  has_column_privilege(current_user,'public.user_account','password_hash','SELECT') AS credential_read,
                  (SELECT count(*) FROM pg_policies p JOIN pg_class c ON c.relname=p.tablename
                    AND c.relnamespace='public'::regnamespace
                    WHERE p.schemaname='public' AND p.tablename IN
                      ('margin_account','order','order_history','position','order_request_identity')
                    AND p.policyname='financial_service_read' AND p.roles=ARRAY[current_user]::name[]
                    AND p.cmd='SELECT' AND p.qual='true' AND c.relrowsecurity AND c.relforcerowsecurity) AS protected_tables""").fetchone()
                if boundary['admin_member'] or boundary['credential_read'] or boundary['protected_tables']!=5:
                    raise RuntimeError('Financial database identity boundary is not installed')

            if not conn.execute("SELECT pg_try_advisory_lock(hashtext('tradegraph-matching-owner')) AS locked").fetchone()['locked']:
                raise RuntimeError('Another matching owner is active')
            if conn.execute("SELECT EXISTS(SELECT 1 FROM public.\"order\" WHERE status IN ('OPEN','PARTIAL')) AS pending").fetchone()['pending']:
                raise RuntimeError('Unresolved active orders: operator reconciliation required')
            return conn
        except BaseException:
            conn.close()
            raise

    @contextmanager
    def admin_context(self):
        s=self.settings
        connection=(self._connect_as(s.postgres_compliance_user,s.postgres_compliance_password)
                    if s.database_identity_mode=='isolated' else self.connect())
        with connection as conn:
            conn.execute('SET LOCAL ROLE compliance_admin_role')
            conn.execute("SET LOCAL app.role='COMPLIANCE_ADMIN'")
            yield conn
