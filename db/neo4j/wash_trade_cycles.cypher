// Closed rings are investigation candidates, never proof of misconduct.
MATCH path=(a:Trader)-[:EXECUTED_AGAINST*3..5]->(a)
WHERE all(n IN nodes(path)[0..-1] WHERE single(m IN nodes(path)[0..-1] WHERE m=n))
  AND a.id=reduce(low=a.id,n IN nodes(path)[0..-1] | CASE WHEN n.id<low THEN n.id ELSE low END)
  AND ($trader_ids IS NULL OR all(n IN nodes(path) WHERE n.id IN $trader_ids))
RETURN [n IN nodes(path)[0..-1] | n.id] AS trader_ids,
       [r IN relationships(path) | r.trade_count] AS edge_counts
LIMIT $limit;
