"""Derived graph: only canonical SQL aggregates, retry-safe without extra entities."""
from datetime import datetime,timedelta,timezone
from neo4j import GraphDatabase,Query
from backend.config import ROOT

MERGE = '''
MERGE (a:Trader {id:$buyer}) SET a.name=$buyer_name
MERGE (b:Trader {id:$seller}) SET b.name=$seller_name
MERGE (a)-[r:EXECUTED_AGAINST]->(b)
ON CREATE SET r.trade_count=0,r.total_notional=0
SET r.trade_count=CASE WHEN r.trade_count=$trade_count-1 THEN r.trade_count+1 ELSE $trade_count END,
    r.total_notional=$total_notional,r.last_traded_at=datetime($last_traded_at)
RETURN r.trade_count AS trade_count,r.total_notional AS total_notional
'''


class Neo4jGraph:
    def __init__(self,settings,database):
        self.database=database
        self.timeout=settings.health_timeout_seconds
        self.driver=GraphDatabase.driver(settings.neo4j_uri,auth=(settings.neo4j_user,settings.neo4j_password),connection_timeout=self.timeout)

    def run(self,query,params=None):
        def wire(value):
            # Psycopg uses zoneinfo; do not pass that tzinfo into Neo4j's
            # temporal codec. Cypher constructs real DATETIME values from ISO.
            if isinstance(value,datetime): return value.astimezone(timezone.utc).isoformat()
            if isinstance(value,dict): return {k:wire(v) for k,v in value.items()}
            if isinstance(value,(list,tuple)): return [wire(v) for v in value]
            return value
        with self.driver.session() as session:
            return [r.data() for r in session.run(Query(query,timeout=self.timeout),wire(params or {}))]

    def initialize(self):
        self.run((ROOT/'db/neo4j/constraints.cypher').read_text())

    def pair(self,buyer,seller,*,retention_cutoff=None):
        rows=self.database.query('''SELECT count(*) AS trade_count,coalesce(sum(e.price_ticks::numeric*i.tick_size*e.quantity),0) AS total_notional,
          max(e.executed_at) AS last_traded_at FROM execution e JOIN instrument i ON i.id=e.instrument_id WHERE e.buy_trader_id=%s AND e.sell_trader_id=%s''',(buyer,seller))
        row=rows[0]
        if not row['trade_count'] or (retention_cutoff is not None and row['last_traded_at']<retention_cutoff):
            self.run('MATCH (a:Trader {id:$a})-[r:EXECUTED_AGAINST]->(b:Trader {id:$b}) DELETE r',{'a':str(buyer),'b':str(seller)})
            return None
        total=int(row['total_notional'])
        if not 0<=total<2**63:
            raise OverflowError('Neo4j aggregate exceeds exact signed-64-bit property range')
        names={str(r['id']):r['full_name'] for r in self.database.query('SELECT id,full_name FROM trader WHERE id=ANY(%s)',([buyer,seller],))}
        params={'buyer':str(buyer),'seller':str(seller),'buyer_name':names[str(buyer)],'seller_name':names[str(seller)],
                'trade_count':row['trade_count'],'total_notional':total,'last_traded_at':row['last_traded_at']}
        # +1 is used for a new canonical fill; replay/backlog uses absolute counts.
        return self.run(MERGE,params)[0]

    def apply(self,event):
        return self.pair(event.buy_trader_id,event.sell_trader_id)

    def apply_committed(self,event):
        # Historical outbox backfill must not resurrect relationships removed by
        # the existing 90-day inactivity policy. Recent live delivery is unchanged.
        cutoff=datetime.now(timezone.utc)-timedelta(days=90)
        if event.occurred_at<cutoff:
            return self.pair(event.buy_trader_id,event.sell_trader_id,retention_cutoff=cutoff)
        return self.apply(event)

    def rebuild(self,trader_ids=None):
        scope=trader_ids if trader_ids is not None else [r['id'] for r in self.database.query('SELECT id FROM trader')]
        pairs=self.database.query('''SELECT e.buy_trader_id AS buyer,e.sell_trader_id AS seller,
          a.full_name AS buyer_name,b.full_name AS seller_name,count(*) AS trade_count,
          sum(e.price_ticks::numeric*i.tick_size*e.quantity) AS total_notional,max(e.executed_at) AS last_traded_at
          FROM execution e JOIN instrument i ON i.id=e.instrument_id JOIN trader a ON a.id=e.buy_trader_id JOIN trader b ON b.id=e.sell_trader_id
          WHERE e.buy_trader_id=ANY(%s) AND e.sell_trader_id=ANY(%s)
          GROUP BY e.buy_trader_id,e.sell_trader_id,a.full_name,b.full_name''',(scope,scope))
        for row in pairs:
            row['buyer'],row['seller']=str(row['buyer']),str(row['seller'])
            row['total_notional']=int(row['total_notional'])
            if not 0<=row['total_notional']<2**63: raise OverflowError('Neo4j aggregate exceeds integer property range')
        self.run((ROOT/'db/neo4j/seed.cypher').read_text(),{'pairs':pairs})
        canonical={(row['buyer'],row['seller']) for row in pairs}
        existing=self.run('MATCH (a:Trader)-[:EXECUTED_AGAINST]->(b:Trader) WHERE a.id IN $ids AND b.id IN $ids RETURN a.id AS buyer,b.id AS seller',{'ids':[str(x) for x in scope]})
        for row in existing:
            if (row['buyer'],row['seller']) not in canonical:
                self.run('MATCH (a:Trader {id:$buyer})-[r:EXECUTED_AGAINST]->(b:Trader {id:$seller}) DELETE r',row)
        return len(pairs)

    def cycles(self,limit=25,trader_ids=None):
        scope=trader_ids if trader_ids is not None else [r['id'] for r in self.database.query('SELECT id FROM trader')]
        return self.run((ROOT/'db/neo4j/wash_trade_cycles.cypher').read_text(),{'limit':limit,'trader_ids':[str(x) for x in scope]})

    def retention(self,cutoff=None,trader_ids=None):
        scope=trader_ids if trader_ids is not None else [r['id'] for r in self.database.query('SELECT id FROM trader')]
        return self.run((ROOT/'db/neo4j/retention.cypher').read_text(),{'cutoff':cutoff or datetime.now(timezone.utc)-timedelta(days=90),'trader_ids':[str(x) for x in scope]})[0]['removed']

    def remove_owned_nodes(self,trader_ids):
        # Test/demo cleanup only: caller must supply its newly created identities.
        self.run('MATCH (t:Trader) WHERE t.id IN $ids DETACH DELETE t',{'ids':[str(x) for x in trader_ids]})

    def close(self): self.driver.close()
