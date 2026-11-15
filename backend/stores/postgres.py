"""Least-privileged service connections; every call has an explicit commit boundary."""
from contextlib import contextmanager
import psycopg
from psycopg.rows import dict_row
from decimal import Decimal
from backend.config import ROOT


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

    def connect(self, **kwargs):
        s = self.settings
        return psycopg.connect(host=s.postgres_host, port=s.postgres_port,
            dbname=s.postgres_db, user=s.postgres_runtime_user,
            password=s.postgres_runtime_password, connect_timeout=s.health_timeout_seconds,
            options='-c statement_timeout=30000 -c lock_timeout=10000',
            row_factory=dict_row, **kwargs)

    def query(self, sql, params=()):
        with self.connect() as conn:
            return conn.execute(sql, params).fetchall()

    def identity(self, subject):
        rows = self.query('SELECT u.id,u.role,t.id AS trader_id FROM user_account u LEFT JOIN trader t ON t.user_account_id=u.id WHERE u.id=%s', (subject,))
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

    def reserve(self, trader_id, request):
        with self.connect() as conn:
            conn.execute("SET LOCAL app.role='TRADER'")
            order_id = conn.execute('SELECT public.place_and_reserve_order(%s,%s,%s,%s,%s) AS id',
                (trader_id, request.instrument_id, request.side, request.price_ticks, request.quantity)).fetchone()['id']
            row = conn.execute('SELECT * FROM public."order" WHERE id=%s', (order_id,)).fetchone()
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
        return applied  # financial acknowledgement only after COMMIT

    def cancel(self, order_id, trader_id):
        with self.connect() as conn:
            conn.execute("SET LOCAL app.role='TRADER'")
            quantity = conn.execute('SELECT public.cancel_order(%s,%s) AS quantity',(order_id,trader_id)).fetchone()['quantity']
        return quantity

    def acquire_owner(self):
        conn = self.connect(autocommit=True)
        try:
            row = conn.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls,rolinherit FROM pg_roles WHERE rolname=current_user').fetchone()
            if any(row.values()):
                raise RuntimeError('Runtime login must be nonprivileged and NOINHERIT')
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
        with self.connect() as conn:
            conn.execute('SET LOCAL ROLE compliance_admin_role')
            conn.execute("SET LOCAL app.role='COMPLIANCE_ADMIN'")
            yield conn
