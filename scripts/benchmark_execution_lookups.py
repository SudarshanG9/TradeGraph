"""Rollback-only planner probe on a temporary execution clone; no financial writes."""
import json
from pathlib import Path
from scripts.verify_schema import db_connect

INDEXES = '''
CREATE INDEX idx_execution_buy_order ON public.execution(buy_order_id);
CREATE INDEX idx_execution_sell_order ON public.execution(sell_order_id);
CREATE INDEX idx_execution_buy_instrument_id ON public.execution(buy_trader_id,instrument_id,id);
CREATE INDEX idx_execution_sell_instrument_id ON public.execution(sell_trader_id,instrument_id,id);
'''

def run():
    with db_connect() as conn:
        conn.execute('CREATE TEMP TABLE hardening_execution (LIKE public.execution INCLUDING INDEXES) ON COMMIT DROP')
        conn.execute('''INSERT INTO hardening_execution
          SELECT g,g%1000+1,g*2,g*2+1,md5((g%10)::text)::uuid,
          md5((g%11+20)::text)::uuid,100,1,now() FROM generate_series(1,50000) g''')
        conn.execute('ANALYZE hardening_execution')
        queries = {
            'fee_lookup': 'SELECT sum(quantity) FROM hardening_execution WHERE buy_order_id=50000 OR sell_order_id=50000',
            'position_lookup': "SELECT * FROM hardening_execution WHERE instrument_id=2 AND (buy_trader_id=md5('1')::uuid OR sell_trader_id=md5('1')::uuid) ORDER BY id",
        }
        queries['position_seller_lookup'] = queries['position_lookup'].replace("md5('1')", "md5('21')")
        results = {}
        for phase in ('before','after'):
            if phase == 'after':
                conn.execute(INDEXES.replace('public.execution','hardening_execution'), prepare=False)
                conn.execute('ANALYZE hardening_execution')
            results[phase] = {}
            for name, query in queries.items():
                results[phase][name] = conn.execute('EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) '+query).fetchone()[0][0]
        conn.rollback()
        return results

if __name__ == '__main__':
    print(json.dumps(run(),indent=2))
