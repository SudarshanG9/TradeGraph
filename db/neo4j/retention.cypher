// Scope to known PostgreSQL trader IDs; never delete unrelated graph data.
MATCH (a:Trader)-[r:EXECUTED_AGAINST]->(b:Trader)
WHERE a.id IN $trader_ids AND b.id IN $trader_ids AND r.last_traded_at < datetime($cutoff)
WITH collect(r) AS edges
FOREACH(r IN edges | DELETE r)
RETURN size(edges) AS removed;
