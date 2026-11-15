-- Each desk is a root of its own subtree; cycle guard also handles corrupt cycles.
-- Volume is trader-leg volume: a same-desk trade contributes both traders' legs.
WITH RECURSIVE tree(root,id,path) AS (
 SELECT id,id,ARRAY[id] FROM public.desk
 UNION ALL
 SELECT tree.root,d.id,tree.path||d.id FROM public.desk d JOIN tree ON d.parent_desk_id=tree.id WHERE NOT d.id=ANY(tree.path)
), facts AS (
 SELECT t.id,t.desk_id,
  (SELECT coalesce(sum(p.realized_pnl),0) FROM public.position p WHERE p.trader_id=t.id) AS pnl,
  (SELECT coalesce(sum(e.quantity),0) FROM public.execution e WHERE e.buy_trader_id=t.id OR e.sell_trader_id=t.id) AS volume
 FROM public.trader t
)
SELECT tree.root AS desk_id,coalesce(sum(facts.pnl),0) AS realized_pnl,coalesce(sum(facts.volume),0) AS execution_volume
FROM tree LEFT JOIN facts ON facts.desk_id=tree.id GROUP BY tree.root ORDER BY tree.root;
