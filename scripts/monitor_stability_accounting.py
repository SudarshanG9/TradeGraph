"""Read-only independent accounting audit for the isolated alternating-trade soak."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from backend.config import Settings
from backend.stores.postgres import Database


def snapshot(database,instrument):
    with database.connect() as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        rows=conn.execute('SELECT * FROM execution WHERE instrument_id=%s ORDER BY id',(instrument,)).fetchall()
        if not rows:return None
        first=rows[0]
        actors=(first['buy_trader_id'],first['sell_trader_id'])
        n=len(rows)
        for index,row in enumerate(rows):
            buyer,seller=actors if index%2==0 else tuple(reversed(actors))
            assert row['buy_trader_id']==buyer and row['sell_trader_id']==seller
            assert row['quantity']==1 and row['price_ticks']==100
        accounts=conn.execute('SELECT trader_id,cash_balance,escrow_balance FROM margin_account WHERE trader_id=ANY(%s)',(list(actors),)).fetchall()
        balances={r['trader_id']:r['cash_balance']+r['escrow_balance'] for r in accounts}
        assert balances[actors[0]]==20000-n-(100 if n%2 else 0)
        assert balances[actors[1]]==20000-n+(100 if n%2 else 0)
        positions=conn.execute('SELECT trader_id,net_quantity,realized_pnl FROM position WHERE instrument_id=%s',(instrument,)).fetchall()
        assert {r['trader_id']:r['net_quantity'] for r in positions}=={actors[0]:n%2,actors[1]:-(n%2)}
        assert all(r['realized_pnl']==0 for r in positions)
        assert len({r['id'] for r in rows})==n
        return {'executions':n,'combined_cash_and_escrow':sum(balances.values()),'expected_total':40000-2*n,
                'escrow':sum(r['escrow_balance'] for r in accounts),'position_sum':sum(r['net_quantity'] for r in positions),
                'gross_realized_pnl':0,'unique_execution_ids':n,'verified':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--timeout',type=int,default=1900)
    args=parser.parse_args()
    settings=Settings.from_env()
    if not settings.postgres_db.startswith('tradegraph_test_'):raise ValueError('Explicit test database required')
    db=Database(settings)
    candidates=db.query("SELECT DISTINCT e.instrument_id FROM execution e JOIN instrument i ON i.id=e.instrument_id WHERE i.symbol LIKE %s",('T%',))
    if len(candidates)!=1:raise ValueError('Exactly one synthetic soak instrument required')
    instrument=candidates[0]['instrument_id']
    began=time.monotonic();samples=[]
    result={'started_at':datetime.now(timezone.utc).isoformat(),'mode':'read_only','status':'RUNNING','samples':samples}
    while time.monotonic()-began<args.timeout:
        value=snapshot(db,instrument)
        if value is None:
            result['status']='PASS: scoped fixture completed and was cleaned';break
        samples.append({'elapsed_seconds':time.monotonic()-began,**value})
        result['elapsed_seconds']=time.monotonic()-began
        args.output.write_text(json.dumps(result,indent=2))
        time.sleep(5)
    else:result['status']='TIMEOUT: last samples verified; fixture still present'
    result['finished_at']=datetime.now(timezone.utc).isoformat()
    args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps({'status':result['status'],'samples':len(samples),'last':samples[-1] if samples else None}))


if __name__=='__main__':main()
