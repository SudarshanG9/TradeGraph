"""Read-only financial source; benchmark pair aggregation on a temporary clone."""
import json
from uuid import UUID
from scripts.verify_schema import db_connect


def run():
    with db_connect() as conn:
        conn.execute('CREATE TEMP TABLE graph_pair_probe (LIKE execution INCLUDING ALL) ON COMMIT DROP')
        instrument=conn.execute('SELECT id FROM instrument ORDER BY id LIMIT 1').fetchone()[0]
        conn.execute('''INSERT INTO graph_pair_probe(id,instrument_id,buy_order_id,sell_order_id,buy_trader_id,sell_trader_id,price_ticks,quantity,executed_at)
          SELECT g,%s,2*g,2*g+1,md5('buyer'||(g%%100))::uuid,md5('seller'||(g%%100))::uuid,100,1,now() FROM generate_series(1,50000) g''',(instrument,))
        # The source schema may already have the candidate index in the isolated
        # environment; remove only its TEMP clone to measure the prior path.
        for name,definition in conn.execute("SELECT indexname,indexdef FROM pg_indexes WHERE tablename='graph_pair_probe'").fetchall():
            if '(buy_trader_id, sell_trader_id)' in definition:
                from psycopg import sql
                conn.execute(sql.SQL('DROP INDEX {}').format(sql.Identifier(name)))
        conn.execute('ANALYZE graph_pair_probe')
        query='''SELECT count(*),coalesce(sum(e.price_ticks::numeric*i.tick_size*e.quantity),0),max(e.executed_at)
          FROM graph_pair_probe e JOIN instrument i ON i.id=e.instrument_id
          WHERE e.buy_trader_id=md5('buyer0')::uuid AND e.sell_trader_id=md5('seller0')::uuid'''
        result={}
        for phase in ('before','after'):
            if phase=='after':
                conn.execute('CREATE INDEX ON graph_pair_probe(buy_trader_id,sell_trader_id) INCLUDE(instrument_id,price_ticks,quantity,executed_at)')
                conn.execute('ANALYZE graph_pair_probe')
            plans=[conn.execute('EXPLAIN(ANALYZE,BUFFERS,FORMAT JSON) '+query).fetchone()[0][0] for _ in range(5)]
            result[phase]={'execution_ms':[p['Execution Time'] for p in plans],'last_plan':plans[-1]}
        result['note']='50,000-row temporary execution clone; five warm probes, no production writes or throughput claim. Pair history still scanned.'
        return result


if __name__=='__main__':print(json.dumps(run(),indent=2))
