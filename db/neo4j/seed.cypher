// Supply pairs computed from committed PostgreSQL executions, never invented fills.
UNWIND $pairs AS pair
MERGE (a:Trader {id:pair.buyer}) SET a.name=pair.buyer_name
MERGE (b:Trader {id:pair.seller}) SET b.name=pair.seller_name
MERGE (a)-[r:EXECUTED_AGAINST]->(b)
SET r.trade_count=pair.trade_count,r.total_notional=pair.total_notional,r.last_traded_at=datetime(pair.last_traded_at);
