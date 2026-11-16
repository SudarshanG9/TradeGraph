import pytest
from psycopg.errors import CheckViolation, ForeignKeyViolation, UniqueViolation



@pytest.mark.day1
def test_thirteen_tables(db_conn):
    with db_conn.cursor() as cur:
        cur.execute(
            """SELECT count(*) FROM information_schema.tables
               WHERE table_schema='public' AND table_type='BASE TABLE'"""
        )
        assert cur.fetchone()[0] == 14
        from scripts.verify_schema import EXPECTED_TABLES
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")
        assert {r[0] for r in cur.fetchall()} == EXPECTED_TABLES | {'order_request_identity'}


@pytest.mark.day1
def test_static_seeds_and_hierarchy(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM instrument")
        assert cur.fetchone()[0] == 3
        cur.execute("SELECT count(*) FROM fee_tier")
        assert cur.fetchone()[0] == 2
        cur.execute(
            """SELECT parent.name FROM desk child
               JOIN desk parent ON child.parent_desk_id = parent.id
               WHERE child.name = 'Equities'"""
        )
        assert cur.fetchone()[0] == "Global Trading"


@pytest.mark.day1
def test_invalid_tick_size_rejected(db_conn):
    with db_conn.cursor() as cur, pytest.raises(CheckViolation):
        cur.execute(
            "INSERT INTO instrument(symbol,tick_size,lot_size) VALUES (%s,%s,%s)",
            ("BAD_TICK", -1, 1),
        )


@pytest.mark.day1
def test_invalid_user_role_rejected(db_conn):
    with db_conn.cursor() as cur, pytest.raises(CheckViolation):
        cur.execute(
            "INSERT INTO user_account(email,password_hash,role) VALUES (%s,%s,%s)",
            ("invalid@tradegraph.test", "not-a-hash", "ROOT"),
        )


@pytest.mark.day1
def test_negative_balance_rejected(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT trader_id FROM margin_account LIMIT 1")
        trader_id = cur.fetchone()[0]
        with pytest.raises(CheckViolation):
            cur.execute(
                "UPDATE margin_account SET cash_balance=-1 WHERE trader_id=%s",
                (trader_id,),
            )


@pytest.mark.day1
def test_invalid_trader_fk_rejected(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM instrument LIMIT 1")
        instrument_id = cur.fetchone()[0]
        with pytest.raises(ForeignKeyViolation):
            cur.execute(
                """INSERT INTO "order"
                   (trader_id,instrument_id,side,price_ticks,quantity)
                   VALUES (%s,%s,'BUY',100,1)""",
                ("00000000-0000-0000-0000-000000000000", instrument_id),
            )


@pytest.mark.day1
def test_duplicate_instrument_symbol_rejected(db_conn):
    with db_conn.cursor() as cur, pytest.raises(UniqueViolation):
        cur.execute(
            "INSERT INTO instrument(symbol,tick_size,lot_size) VALUES ('ACME',1,1)"
        )


@pytest.mark.day1
def test_invalid_filled_quantity_rejected(db_conn):
    with db_conn.cursor() as cur:
        cur.execute("SELECT id FROM trader LIMIT 1")
        trader_id = cur.fetchone()[0]
        cur.execute("SELECT id FROM instrument LIMIT 1")
        instrument_id = cur.fetchone()[0]
        with pytest.raises(CheckViolation):
            cur.execute(
                """INSERT INTO "order"
                   (trader_id,instrument_id,side,price_ticks,quantity,filled_quantity)
                   VALUES (%s,%s,'BUY',100,10,11)""",
                (trader_id, instrument_id),
            )


@pytest.mark.day1
def test_order_history_no_auto_generated_id(db_conn):
    with db_conn.cursor() as cur:
        cur.execute(
            """SELECT column_default FROM information_schema.columns
               WHERE table_schema='public' AND table_name='order_history' AND column_name='id'"""
        )
        assert cur.fetchone()[0] is None


@pytest.mark.parametrize(
    ("trader_email", "status", "error"),
    [("missing@tradegraph.test", "FILLED", ForeignKeyViolation),
     ("alice@tradegraph.test", "OPEN", CheckViolation)],
)
@pytest.mark.day1
def test_archive_integrity(db_conn, trader_email, status, error):
    with db_conn.cursor() as cur, pytest.raises(error):
        cur.execute(
            """INSERT INTO order_history
                   (id,trader_id,instrument_id,side,price_ticks,quantity,
                    filled_quantity,status,created_at,updated_at)
               SELECT -1, coalesce((SELECT t.id FROM trader t JOIN user_account u
                                    ON t.user_account_id=u.id WHERE u.email=%s),
                                   '00000000-0000-0000-0000-000000000000'::uuid),
                      id, 'BUY', 100, 1, 1, %s, now(), now()
               FROM instrument WHERE symbol='ACME'""",
            (trader_email, status),
        )


@pytest.mark.day1
def test_position_composite_key(db_conn):
    with db_conn.cursor() as cur:
        cur.execute(
            """SELECT pg_get_constraintdef(oid) FROM pg_constraint
               WHERE conrelid='position'::regclass AND contype='p'"""
        )
        assert "(trader_id, instrument_id)" in cur.fetchone()[0]


# Phase 5: real query results, atomic scoped archive and measured access paths.
from pathlib import Path
from datetime import datetime,timedelta,timezone
from tests.integration.test_order_pipeline import accounts
from tests.concurrency.test_settlement_locks import reserve,make_event
from backend.config import Settings
from backend.stores.postgres import Database,query_text


def test_advanced_queries_view_and_atomic_archive(accounts):
    users,instrument=accounts
    a,b=users[:2]
    db=Database(Settings.from_env())
    baseline={r['desk_id']:r['execution_volume'] for r in db.named('rollup')}
    with db_conn_for_archive() as conn:
        desk=conn.execute("SELECT id FROM desk WHERE name='Equities'").fetchone()[0]
        conn.execute('UPDATE trader SET desk_id=%s WHERE id=ANY(%s)',(desk,[a['trader_id'],b['trader_id']]))
    buy=reserve(a,instrument,'BUY',100,3); sell=reserve(b,instrument,'SELL',100,2)
    db.settle(make_event(buy,sell,a,b,instrument,100,2))
    bands=db.named('bands',{'minimum_volume':1})
    assert any(r['instrument_id']==instrument and r['price_ticks']==100 and r['band_volume']>=2 for r in bands)
    vwap=db.named('vwap',{'instrument_id':instrument})
    assert any(r['vwap_ticks'].startswith('100') for r in vwap)
    sets=db.named('maker_taker')
    assert {'classification':'maker_only','trader_id':a['trader_id']} in sets
    high=reserve(a,instrument,'BUY',200,1)
    assert high in [r['id'] for r in db.named('nested_range',{'instrument_id':instrument})]
    assert high in [r['id'] for r in db.named('correlated_orders')]
    with db.admin_context() as conn:
        row=conn.execute("SELECT remaining_quantity FROM public.order_book_view WHERE instrument_id=%s AND side='BUY' AND price_ticks=100",(instrument,)).fetchone()
        assert row['remaining_quantity']>=1
    db.cancel(buy,a['trader_id'])
    with db_conn_for_archive() as conn:
        # Only fixture-owned traders; no archive write touches existing user orders.
        params={'cutoff':datetime.now(timezone.utc)+timedelta(seconds=1),'trader_ids':[a['trader_id'],b['trader_id']]}
        moved=conn.execute(query_text('archive'),params).fetchall()
        assert {r[0] for r in moved}=={buy,sell}
        assert conn.execute(query_text('archive'),params).fetchall()==[]
        assert conn.execute('SELECT id FROM public."order" WHERE id=%s',(high,)).fetchone()
        assert conn.execute('SELECT count(*) FROM execution WHERE buy_order_id=%s',(buy,)).fetchone()[0]==1
        # Nested savepoint rollback restores both DELETE and INSERT together.
        conn.rollback()
    with db_conn_for_archive() as conn:
        assert conn.execute('SELECT id FROM public."order" WHERE id=%s',(buy,)).fetchone()
        assert not conn.execute('SELECT id FROM order_history WHERE id=%s',(buy,)).fetchone()
    rolled={r['desk_id']:r['execution_volume'] for r in db.named('rollup')}
    assert rolled[desk]==baseline[desk]+4
    assert db.optimizer('price_band',instrument,90,110)['dataset_size']>=1


def test_sql_ten_minute_window_excludes_old_fill(accounts):
    from dataclasses import replace
    users,instrument=accounts
    a,b=users[:2]
    db=Database(Settings.from_env())
    first=reserve(a,instrument,'BUY',100,2); other=reserve(b,instrument,'SELL',100,2)
    db.settle(replace(make_event(first,other,a,b,instrument,100,2),occurred_at=datetime.now(timezone.utc)-timedelta(minutes=11)))
    first=reserve(a,instrument,'BUY',200,1); other=reserve(b,instrument,'SELL',200,1)
    db.settle(make_event(first,other,a,b,instrument,200,1))
    from decimal import Decimal
    rows=db.named('vwap',{'instrument_id':instrument})
    assert [Decimal(r['vwap_ticks']) for r in rows]==[100,200]


def db_conn_for_archive():
    from scripts.verify_schema import db_connect
    return db_connect()


def test_optimizer_real_execution_lab(db_conn):
    """4,000 financially settled fills, 40 pairs; all lab data rolls back."""
    import os,json,time,bcrypt
    from uuid import uuid4
    from psycopg.rows import dict_row
    base=datetime.now(timezone.utc)-timedelta(seconds=4000)
    hashed=bcrypt.hashpw(b'optimizer-only-synthetic',bcrypt.gensalt()).decode()
    instrument=db_conn.execute("SELECT id FROM instrument WHERE symbol='ACME'").fetchone()[0]
    tier=db_conn.execute("SELECT id FROM fee_tier WHERE tier_name='STANDARD'").fetchone()[0]
    started=time.perf_counter()
    for pair in range(40):
        traders=[]
        for _ in range(2):
            uid=db_conn.execute("INSERT INTO user_account(email,password_hash,role) VALUES (%s,%s,'TRADER') RETURNING id",(f'optimizer-{uuid4()}@tradegraph.test',hashed)).fetchone()[0]
            tid=db_conn.execute("INSERT INTO trader(user_account_id,full_name) VALUES (%s,'Synthetic optimizer') RETURNING id",(uid,)).fetchone()[0]
            db_conn.execute('INSERT INTO margin_account(trader_id,cash_balance,fee_tier_id) VALUES (%s,1000000000,%s)',(tid,tier))
            traders.append(tid)
        price=1000+pair
        ids=[db_conn.execute('SELECT public.place_and_reserve_order(%s,%s,%s,%s,100)',(tid,instrument,side,price)).fetchone()[0] for tid,side in zip(traders,('BUY','SELL'))]
        results=db_conn.execute("SELECT public.settle_execution(nextval('execution_id_seq'),%s,%s,%s,%s,%s,%s,1,%s,%s::timestamptz+(%s+g)*interval '1 second') FROM generate_series(1,100) g",
            (instrument,*ids,*traders,price,ids[1],base,pair*100)).fetchall()
        assert all(r[0] for r in results)
    db_conn.execute('ANALYZE public.execution')
    cases={
        'forced_sequential':('SELECT sum(quantity) FROM execution WHERE instrument_id=%s AND price_ticks=1020',(instrument,),['SET LOCAL enable_indexscan=off','SET LOCAL enable_bitmapscan=off','SET LOCAL enable_indexonlyscan=off']),
        'automatic_covering':('SELECT sum(quantity) FROM execution WHERE instrument_id=%s AND price_ticks=1020',(instrument,),[]),
        'automatic_btree':('SELECT id FROM execution WHERE instrument_id=%s AND executed_at>=%s',(instrument,base+timedelta(seconds=3950)),[]),
        'automatic_time':('SELECT count(*) FROM execution WHERE executed_at>=%s',(base+timedelta(seconds=3950),),[]),
        'forced_brin_teaching':('SELECT count(*) FROM execution WHERE executed_at>=%s',(base+timedelta(seconds=3950),),['SET LOCAL enable_seqscan=off','SET LOCAL enable_indexscan=off','SET LOCAL enable_indexonlyscan=off']),
    }
    plans={}
    for name,(query,params,settings) in cases.items():
        db_conn.execute('SAVEPOINT optimizer_plan')
        for setting in settings: db_conn.execute(setting)
        plans[name]=db_conn.execute('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+query,params).fetchone()[0][0]
        db_conn.execute('ROLLBACK TO SAVEPOINT optimizer_plan')
    assert plans['automatic_covering']['Plan']['Actual Rows']==1
    result={'rows':4000,'seed_seconds':time.perf_counter()-started,'plans':plans,'note':'Uncommitted real settled rows; visibility map not vacuumed. Forced plans are labelled; no forced speedup claim.'}
    if os.environ.get('TRADEGRAPH_PLAN_REPORT'):
        Path(os.environ['TRADEGRAPH_PLAN_REPORT']).write_text(json.dumps(result,indent=2))
    db_conn.rollback()
    db_conn.execute('ANALYZE public.execution')


def test_installer_refuses_placeholder_for_existing_runtime_identity():
    import os,subprocess,sys,hashlib
    from backend.config import Settings
    settings=Settings.from_env()
    env=os.environ.copy();env['POSTGRES_RUNTIME_USER']=settings.postgres_runtime_user
    env['POSTGRES_RUNTIME_PASSWORD']='replace_with_runtime_password'
    path=Path('.env')
    before=hashlib.sha256(path.read_bytes()).hexdigest()
    result=subprocess.run(['bash','scripts/setup_backend.sh','--phase','5'],env=env,capture_output=True,text=True,timeout=30)
    assert result.returncode!=0
    assert 'requires its current password' in result.stderr
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    assert Database(settings).query('SELECT 1 AS healthy')[0]['healthy']==1


@pytest.mark.parametrize('side',['BUY','SELL'])
@pytest.mark.parametrize('maker',[True,False])
@pytest.mark.parametrize('fills', [[],[1],[1,1],[3]])
def test_exact_fee_refunds_after_single_multiple_and_no_fill(accounts,side,maker,fills):
    from fractions import Fraction
    from tests.concurrency.test_settlement_locks import state
    users,instrument=accounts;a,b=users[:2];db=Database(Settings.from_env())
    price=500000000000001;initial=10**17;quantity=3
    with db_conn_for_archive() as conn:
        conn.execute('UPDATE margin_account SET cash_balance=%s WHERE trader_id=ANY(%s)',(initial,[a['trader_id'],b['trader_id']]))
    opposite='SELL' if side=='BUY' else 'BUY'
    if maker:
        subject=reserve(a,instrument,side,price,quantity);other=reserve(b,instrument,opposite,price,quantity)
    else:
        other=reserve(b,instrument,opposite,price,quantity);subject=reserve(a,instrument,side,price,quantity)
    for amount in fills:
        event=make_event(subject,other,a,b,instrument,price,amount) if side=='BUY' else make_event(other,subject,b,a,instrument,price,amount)
        db.settle(event)
    filled=sum(fills)
    if filled<quantity: db.cancel(subject,a['trader_id']);db.cancel(other,b['trader_id'])
    fee=Fraction(price*filled*(1 if maker else 2),10000)
    assessed=-(-fee.numerator//fee.denominator)
    expected=initial+(-1 if side=='BUY' else 1)*price*filled-assessed
    assert state(a)==(expected,0)
    if filled<quantity:
        assert db.cancel(subject,a['trader_id'])==0
        assert state(a)==(expected,0)


def test_intersect_except_demonstrations_include_both_maker_and_taker(accounts):
    users,instrument=accounts;a,b=users[:2];db=Database(Settings.from_env())
    buy=reserve(a,instrument,'BUY',100,1);sell=reserve(b,instrument,'SELL',100,1)
    db.settle(make_event(buy,sell,a,b,instrument,100,1))
    buy=reserve(b,instrument,'BUY',100,1);sell=reserve(a,instrument,'SELL',100,1)
    db.settle(make_event(buy,sell,b,a,instrument,100,1))
    rows=db.named('maker_taker')
    for trader in (a['trader_id'],b['trader_id']):
        assert {'classification':'both','trader_id':trader} in rows
        assert {'classification':'either','trader_id':trader} in rows
        assert {'classification':'maker_only','trader_id':trader} not in rows
