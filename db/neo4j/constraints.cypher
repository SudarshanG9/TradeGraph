CREATE CONSTRAINT tradegraph_trader_id_unique IF NOT EXISTS FOR (t:Trader) REQUIRE t.id IS UNIQUE;
