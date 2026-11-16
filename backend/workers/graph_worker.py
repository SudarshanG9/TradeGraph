from backend.events.dispatcher import ReplaceableWorker


class GraphWorker(ReplaceableWorker):
    @property
    def failed(self):
        return self._worker_failure or getattr(self,'delivery_failure',None)

    @failed.setter
    def failed(self,value):
        self._worker_failure=value

    def __init__(self,store,dispatcher):
        self.store=store
        self.ready=False
        super().__init__('neo4j',self.handle,dispatcher,
            key=lambda event:None if event is None else (event.buy_trader_id,event.sell_trader_id))

    def handle(self,event):
        if event is None:
            # Rebuild and durable pair updates share one projection writer lock.
            # Otherwise a slow startup rebuild could replace a newer aggregate.
            with self.store.database.connect() as conn:
                conn.execute('SELECT pg_advisory_xact_lock(hashtext(%s))',('tradegraph-outbox-graph',))
                self.store.initialize()
                self.store.rebuild()
                self.store.retention()
            self.ready=True
        else:
            self.store.apply(event)
